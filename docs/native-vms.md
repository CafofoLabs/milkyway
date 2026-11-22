# Native Linux VM recipes

MilkyWay supplies a `default-linux-vm` base and a `hermes-agent` application recipe. Consumers own placement, VM IDs, configuration, authorization catalogs, encrypted state and execution. Recipes configure each new clone; they never bake Tailscale state, workload identities or provider keys into the reusable Debian image.

## Composition

`tofu/modules/linux-vms` creates protected full clones with DHCP bootstrap, a non-root operator, the guest agent and an explicit node allowlist. It does not provision identities or install applications. The consumer must reject destructive plans and verify each SSH host identity independently before guest configuration.

Set `vm.cpu_type: host` in a native VM map to expose the physical CPU's instructions. Omitted CPU types retain `x86-64-v3`. Changing CPU type requires a full guest shutdown and start; `host` also requires compatible physical CPUs when migrating between nodes.

The cloud-init SSH key only applies at creation: `platform_baseline` disables cloud-init after the first boot. The module therefore ignores later changes to `initialization[0].user_account[0].keys`, so a plan from another control node with a different public key file stays a no-op. Rotate access to existing guests through the SSH CA, not this key.

### Disk growth

Increasing `vm.disk_gb` resizes the `scsi0` disk online, without a reboot (`reboot_after_update = false`). The provider refuses to shrink a disk; a size never goes back down. After the resize, setup grows the root partition and filesystem inside the guest (`ansible/roles/default_linux_vm/tasks/root_disk.yml`, right after the baseline):

- installs `cloud-guest-utils`, reads the root source and type with `findmnt` and fails with a message unless it is ext4 directly on a disk partition (LVM, XFS and other layouts are grown manually);
- rescans the parent disk, runs `growpart` on the root partition and reports a change only on `CHANGED` (`NOCHANGE` is success);
- runs `resize2fs` online only when the filesystem block count is below the partition size.

A second run reports no change in these tasks. Verify with `df -h /` in the guest. Growth uses only free space directly after the root partition.

`ansible/roles/default_linux_vm` configures the Debian baseline, private Tailscale access, SSH CA, firewall cutover and the existing checksum-pinned native Alloy collector. It installs the shared identity/secret clients and delivers an individual workload credential plus non-secret environment bindings. Workload users have no sudo privileges. Docker and Periphery are excluded.

`app-templates/hermes-agent/template.yaml` composes that base. The initial native application runner supports Hermes: it installs the pinned source commit with the checksum-verified upstream installer, selects the provider/model, configures `terminal.backend: local` and supervises the gateway with systemd. Browser binaries and dependencies are opt-in. Without messaging adapters, the gateway runs for scheduled work.

Set `parameters.bot_desktop: true` to provision Hermes' private GUI on the guest. The recipe installs only TigerVNC and the Xfce components required by Bot Desktop, verifies the Hermes-pinned `cua-driver`, installs it when missing or out of sync, and starts the screen as the unprivileged `hermes` user. It also selects a headed browser and enables screen startup on the first GUI tool call. Reapplying the recipe restores these prerequisites after a guest rebuild or Hermes upgrade. The display is served through Hermes' private Unix socket; it does not add a public VNC listener or a graphical login to the Proxmox console. `parameters.browser: true` separately enables Hermes' browser toolset for GUI browsing.

Set `parameters.dashboard: true` to enable a separate native dashboard service on the verified tailnet address, port 9119. Declare HTTPS `HERMES_DASHBOARD_PUBLIC_URL` and `HERMES_DASHBOARD_OIDC_ISSUER` in `env`; the consumer must supply `native_dashboard_client_id` (a public PKCE client) and the exact private `native_dashboard_proxy_address`. Hermes enforces its own OIDC gate, including WebSockets. The consumer owns DNS, TLS routing and IdP group bindings. Key-based provider credentials come from Bao, never a dashboard service file. Disabling the option stops and disables the dashboard service.

## Maps and authorization

`scripts/native_vms.py` compiles version-1 maps containing `name`, `template`, `environment`, `vm`, `parameters`, `env`, `secret_env` and optional `authentik`, `software`, `profiles` and `approval_lists` (see [Hermes profiles](#hermes-profiles) and [Hermes release pin](#hermes-release-pin)). VM identity includes an explicit `vm_id`; consumers check conflicts with existing guests and placement policy. Credential-shaped environment names require a structured reference:

```yaml
secret_env:
  OLLAMA_API_KEY:
    mount: secret
    path: apps/hermes/prod/callisto/providers/ollama
    key: api_key
```

Unknown fields, duplicate YAML keys, path traversal, wildcard paths and protected process-variable overrides fail validation. References never grant access themselves: the existing application identity validator checks them against the administrator-owned catalog. KV v2 permissions apply to the whole path, not individual fields.

For interactive Anthropic OAuth, set `parameters.provider: anthropic`, choose an Anthropic model, and omit `secret_env`. Only this provider supports a map without a provider key. Its service account has no KV read grants. Complete the login in the guest as the `hermes` user with `sudo hermes-agent auth add anthropic --type oauth`; the CLI presents a browser login URL. Hermes keeps its own OAuth state in its private home. A real model request is required after login before accepting the deployment.

Accounts are named `svc-<application>-<environment>-<instance>`. Generated identity manifests aggregate all instances of an application/environment, preserving existing declared accounts when another is added. Each VM receives only its own account from the grouped deployment artifact. The shared M2M foundation must already be provisioned and verified. The recipe does not change human SSO or create provider secret values.

## Hermes profiles

Optional `profiles` and `approval_lists` blocks declare per-profile Hermes settings. `approval_lists` names deny-pattern lists once; profiles reference them by name:

```yaml
parameters:
  provider: ollama-cloud
  model: gpt-oss:120b
approval_lists:
  destructive: ["rm -rf /", "mkfs"]
  network: ["curl * | sh"]
profiles:
  default:
    reasoning_effort: high
    approvals_deny: [destructive]
  reviewer:
    provider: openrouter
    model: example/reviewer-model
    reasoning_effort: medium
    delegation:
      provider: ollama-cloud
      model: gpt-oss:20b
      reasoning_effort: low
    auxiliary:
      vision: {provider: openrouter, model: example/vision-model}
    fallback:
      - {provider: ollama-cloud, model: gpt-oss:120b}
    approvals_deny: [destructive, network]
```

Profile names are `default` or match `[a-z][a-z0-9_-]{0,63}`. Each profile accepts `provider`, `model`, `reasoning_effort`, `delegation` (`provider`, `model`, `reasoning_effort`), `auxiliary` (task names matching `[a-z][a-z0-9_]*`, each with `provider` and `model`), `fallback` (a list of `provider`/`model` routes) and `approvals_deny` (names declared in `approval_lists`). `reasoning_effort` accepts the values Hermes parses: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max` and `ultra`. Named profiles require `provider` and `model`. `parameters` remains the source for the default profile: `profiles.default` may omit `provider` and `model`, and must repeat them exactly if present. Unknown keys, unknown list names and invalid values fail validation with the offending path. Declare the `secret_env` bindings that each profile's providers need; validation checks only the key required by `parameters.provider`.

The compiled map carries each profile with `approvals_deny` resolved to the referenced lists concatenated in order, keeping the first occurrence of each pattern.

The recipe writes `/var/lib/hermes/.hermes/config.yaml` for `default` and `/var/lib/hermes/.hermes/profiles/<name>/config.yaml` for other profiles. It does not create profiles: a declared profile whose directory is missing stops reconciliation before any configuration is written. Create it with Hermes first, then repeat.

Each declared profile is merged into its existing file, keeping every unmanaged key:

- `model.provider` and `model.default` follow the declaration (`parameters` for `default`). `model.reasoning_effort` is always removed, because Hermes reads only `agent.reasoning_effort`.
- `agent.reasoning_effort` is set when declared and removed when not.
- `delegation.provider`, `delegation.model` and `delegation.reasoning_effort` are set or removed to match the declaration; other delegation keys stay.
- Each declared `auxiliary` task gets its `provider` and `model`; its other keys and undeclared tasks stay.
- `fallback_providers` is replaced by the declared `fallback` list and removed when none is declared.
- `approvals.deny` is replaced by the resolved list when `approvals_deny` is declared; other `approvals` keys stay.

The default profile is merged within the existing configuration task, so its file is written once per run. Files are written as the `hermes` user with mode 0600, a private backup of the previous file and suppressed output. A change triggers the same idle-aware gateway and dashboard restarts as other configuration changes. Serialization is deterministic, so repeating a run with the same map reports no change. Maps without `profiles` keep their previous behaviour; undeclared profiles are never touched.

## Hermes release pin

`app-templates/hermes-agent/template.yaml` pins the default upstream release (`release`, `commit`, `installer_sha256`). A map may override that pin with an optional `software` block carrying all three fields, for example to run a canary ahead of the other instances:

```yaml
software:
  release: v1.2.3
  commit: 0123456789abcdef0123456789abcdef01234567
  installer_sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

All three fields are required, unknown fields are rejected, and the values must be a `vX.Y.Z` tag, a full 40-character commit and the SHA-256 of `scripts/install.sh` at that commit. The source-commit check then compares the existing checkout with the map's pin, so an upgrade is a reviewed change of this block followed by setup.

## Declarative Authentik application

Dashboard maps carry an `authentik` block. Consumers pass its normalized application and provider settings to `authentik-baseline`; Terraform contains no per-instance presentation or access defaults. Existing maps without the block keep their previous defaults for compatibility.

```yaml
authentik:
  name: Hermes Callisto
  slug: hermes-callisto
  group: Infrastructure
  description: ""
  publisher: ""
  icon_url: ""
  launch_url: https://hermes.cafofolabs.cloud
  show_in_library: true
  open_in_new_tab: false
  policy_engine_mode: any
  backchannel_providers: []
  access_groups: [platform_admins]
  provider:
    name: Hermes Callisto
    client_type: public
    sub_mode: hashed_user_id
    grant_types: [authorization_code, refresh_token]
    access_token_validity: hours=1
    refresh_token_validity: days=30
    authorization_flow_slug: default-provider-authorization-implicit-consent
    invalidation_flow_slug: default-provider-invalidation-flow
    signing_key_name: authentik Self-signed Certificate
```

`show_in_library: false` sets Authentik's `meta_hide` flag. It hides the card without removing the provider or disabling OIDC. `group` is the application's visual category; `access_groups` are nonempty references to trusted consumer group keys, not display names. `policy_engine_mode` accepts `any` or `all`. Backchannel provider IDs reference providers that already exist; this recipe does not create external sync services.

The `provider` block supports its display name, subject mode, authorization/refresh grants, token validity, and existing authorization-flow, invalidation-flow and signing-certificate names. Omitted flow/certificate references inherit the baseline module's defaults. Hermes requires a public authorization-code/PKCE client; confidential, implicit, password and machine-to-machine grants are rejected. Its strict callback is derived from the dashboard origin. Generated client IDs and credentials remain owned by Terraform and protected delivery.

A custom application slug must match the declared OIDC issuer. Consumers keep stable Terraform resource keys independently of presentation slugs. They must validate reserved names, unique slugs, trusted groups, and the saved plan before applying. Removing access bindings or applications remains subject to their explicit removal safeguards.

See [Authentik application visibility](https://docs.goauthentik.io/add-secure-apps/applications/manage_apps/) and the [pinned provider application schema](https://github.com/goauthentik/terraform-provider-authentik/blob/v2026.5.2/docs/resources/application.md).

## Runtime and rotation

Trusted deployment automation delivers a private artifact containing the individual Authentik app password and connection metadata. No infrastructure provisioning token is delivered. This initial credential cannot be obtained through the identity it bootstraps. Protect its transport, storage and backups; rotate it through the existing identity contract.

When `secret_env` declares keys, `scripts/secret_env.py` authenticates through Authentik, exchanges its JWT for a short-lived Bao token, reads the declared KV v2 paths, checks every required field and revokes the Bao token. With no secret references, it skips machine-credential loading and network authentication. It then replaces itself with Hermes, injecting declared non-secret variables. Provisioning credentials and undeclared provider variables are dropped from the inherited environment. Provider values are never written to `.env`, command arguments or console logs.

For key-based providers, authentication failures and absent/unreadable fields prevent execution; systemd retries after 30 seconds. A running process retains its key until restarted. Changing a KV value alone does not update that process. Authentik and Bao must be available at startup/restart when secret references exist. Provider key rotation and machine-identity password rotation are separate operations. An interactive OAuth login is stored by Hermes and may require a service restart before the gateway uses it.

Persistent Hermes state is under `/var/lib/hermes/.hermes`. Updates preserve sessions, skills and memories. The source-commit check rejects version drift from the template pin or the map's `software` override. If an existing clean checkout already matches the pinned release, the recipe accepts it without rerunning the installer and still reconciles packages, driver and configuration. Back up application data with a tested restore procedure before storing irreplaceable state; this recipe does not implement that backup.

## Access, logs and acceptance

Inside the VM, its administrator runs `sudo hermes-agent` for an interactive CLI using the same scoped identity and current secrets. This sudo command applies to the guest, not the control Mac.

Alloy ships host metrics and journal events. The resolver emits fixed success/failure events without credentials. Gateway stdout/stderr, session files and application log files are excluded from central collection to avoid uploading conversations and provider diagnostics. Private Hermes logs stay local.

Acceptance requires a real model response, denied unrelated secret access, private SSH, recent log/metric ingestion and a separate reboot/recovery check. An active systemd unit, Alloy readiness or successful local tests alone do not prove these conditions.

## Sources

- [Pinned Hermes installer](https://github.com/NousResearch/hermes-agent/blob/2bd378ed1b8d6bf2192cb26e0a55ff3091e6bd19/scripts/install.sh)
- [Hermes v0.23.0](https://github.com/NousResearch/hermes-agent/releases/tag/v0.23.0)
- [Hermes Bot Screen](https://hermes-agent.nousresearch.com/docs/user-guide/features/bot-screen)
- [Hermes providers](https://hermes-agent.nousresearch.com/docs/integrations/providers)
- [Hermes secret helper behavior](https://hermes-agent.nousresearch.com/docs/user-guide/secrets/command)
- [Ollama Cloud authentication](https://docs.ollama.com/api/authentication)
- [OpenBao policies](https://openbao.org/docs/concepts/policies/)


## Browser workspace

Set `parameters.webapp: true` alongside `parameters.dashboard: true` and declare `env.HERMES_WEBAPP_PUBLIC_URL` as a dedicated HTTPS origin. The recipe builds Hermes Desktop's browser bundle with `hermes webapp --build-only` and serves it from the existing system gateway on port 9120. It does not start another gateway or publish VNC. The dashboard continues on port 9119.

The consumer must provision the new HTTPS route, private DNS and an additional strict `<webapp origin>/auth/callback` URI on the instance's existing public OIDC client. The webapp shares dashboard authentication and its exact trusted proxy address, while keeping its own public URL. The guest firewall admits remote TCP/9120 only from that proxy over Tailscale; loopback remains available to native clients.

The system gateway declares external supervision and owns restarts. If a user-level `hermes-gateway.service` is running, reconciliation first stops the competing system retry loop, asks upstream to stop the user gateway without interrupting active sessions, then disables the duplicate user unit. A live-session refusal stops reconciliation; retry after the sessions finish. Existing user unit files remain available for recovery.

Managed fields are merged into the existing configuration, preserving other settings, with private file backups and suppressed configuration output. Reconcile only the intended instance, verify authenticated browser chat, reconnect, terminal and Bot Desktop, then continue to other guests. Disabling `webapp` stops serving the listener after the managed gateway restarts; DNS and IdP removal still require a separate reviewed plan.

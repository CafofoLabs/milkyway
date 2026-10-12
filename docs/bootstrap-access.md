# Bootstrap and private access

MilkyWay reuses Jarvis Ansible deployment patterns. Nimbus owns inventory,
credentials, state locations, orchestration and approval of execution. These
roles do not install Docker on Proxmox or modify host disks, logical volumes,
swap or guest placement.

## Execution order

1. `ansible/playbooks/host-setup.yml` applies a native standalone Proxmox
   bootstrap firewall, enrolls Mercury in Tailscale and provisions a scoped API
   identity. The image/template role is a separate prerequisite for VM creation.
2. OpenTofu creates the identity, vault and platform VMs in the dedicated pool.
3. `guests.yml` waits for cloud-init to finish its first boot, hands subsequent
   guest configuration to Ansible, reconciles hostnames and configures the guest
   firewall, clock, Tailscale and Docker.
4. The consumer publishes DNS records pointing to the discovered tailnet IPs.
5. `core.yml` starts Authentik/PostgreSQL and OpenBao, then private Traefik
   endpoints with DNS-01 certificates. Service credentials persist across runs.
6. Consumer OpenTofu configures Authentik, Bao, groups, OIDC clients, policies,
   machine identities and the SSH CA.
7. The consumer seeds operational external credentials into Bao without
   displaying them, then switches explicitly to operational mode.
8. `credentials.yml` seeds external credentials in bootstrap mode and validates
   their availability from Bao in operational mode.
9. `services.yml` starts observability and Komodo, collects guest telemetry
   with Docker Alloy and physical host telemetry with native Alloy.
10. `lockdown.yml` validates fresh tailnet access, hardens SSH and removes the
   temporary LAN management allowance. Existing bootstrap keys remain available
   for recovery; no permanent service credential is embedded in repository code.

The consumer must execute each approved phase separately. A failed dependency
stops subsequent phases. Service execution is not triggered by publishing code.

## Input contract

Inventory groups are `proxmox`, `platform_vms`, `authentik`, `openbao`,
`traefik`, `observability` and `komodo`. The same guest can belong to several
service groups. Every guest has an explicit `ansible_host`, `ansible_user` and
`ansible_ssh_private_key_file`.

For members of `platform_vms`, `platform_baseline` sets the persistent and
current operating-system hostname to `inventory_hostname` through systemd.
This also converges existing guests when the consumer renames inventory keys;
it does not depend on cloud-init running again. Physical Proxmox hostnames
are left unchanged. Naming conventions belong to the consumer inventory;
MilkyWay does not prescribe planet or moon names.

| Input | Purpose |
| --- | --- |
| `platform_access_mode` | Explicit `bootstrap` or `operational` credential source |
| `platform_initial_management_cidr` | Narrow temporary operator IPv4 source, preferably `/32` |
| `platform_ssh_identity_file` | Existing local SSH private-key path; never its value |
| `platform_tailscale_key_file` | Local protected bootstrap enrollment file |
| `platform_tailscale_tags` | Approved tailnet tags; no policy creation by this role |
| `platform_bao_addr` | Trusted HTTPS vault address in operational mode |
| `platform_bao_token_file` | Opaque local file used by automation to authenticate to Bao |
| `platform_tailscale_secret_path` | Default `platform/tailscale/auth_key`, under KV mount `secret` |
| `platform_ssh_ca_public_key` | Optional public SSH CA key, after Bao configuration |
| `proxmox_api_token_file` | Local protected API token output path |
| `proxmox_tls_ca_file` | Public Proxmox root CA obtained through trusted SSH |
| `proxmox_pool` | Dedicated VM pool, default `nimbus` |
| `proxmox_storage_ids` | Explicit allowed storages, default `local`, `local-lvm` |
| `alloy_metrics_url`, `alloy_logs_url` | Explicit tailnet-only telemetry destinations |

The consumer creates protected local directories before execution. Bootstrap
`.env` loading belongs to the consumer; Ansible receives file paths. Bootstrap
secrets must not appear in CLI arguments, logs, reports or committed files.

The baseline and Docker roles manage their official signed APT source files
directly. Existing `signed-by` keyrings remain mandatory; package installation
refreshes APT metadata and validates repository signatures. This supports minimal
Debian images without adding the obsolete `apt-key` command or an otherwise
unneeded `gpg` dependency solely for the repository module.

## Cloud-init handoff

Cloud-init configures a fresh VM's initial account, SSH host keys and network.
Before changing members of `platform_vms`, `platform_baseline` waits for
`/var/lib/cloud/instance/boot-finished`, then manages the empty root-owned file
`/etc/cloud/cloud-init.disabled`. This is the
[documented cloud-init disable mechanism](https://docs.cloud-init.io/en/latest/howto/disable_cloud_init.html).
It prevents subsequent boots from regenerating host keys or restoring cached
hostnames and `/etc/hosts` entries after Proxmox initialization metadata changes.
The role does not stop running cloud-init stages, clean its cache, remove host
keys or alter the existing persistent network configuration. The completion
marker confirms the final stage ended; it does not prove every first-boot module
succeeded. Any bootstrap errors must be diagnosed and repaired before handoff.

OpenTofu continues to provision fresh VMs and manage their virtual hardware.
After handoff, its cloud-init initialization account, keys and IP settings are
bootstrap inputs; changing them does not reconfigure an existing guest.
Ansible owns subsequent guest configuration. An existing guest IP change needs
an explicitly planned network migration; it must not rely on rerunning
cloud-init. Removing the disable marker requires a separate recovery decision:
changed instance metadata could rerun per-instance modules and rotate host keys.

The immutable Debian template stays unbooted and has no disable marker, so each
new clone runs cloud-init and generates its own host identity before handoff.
Do not use an initialized guest as a new template without a separate image
preparation procedure that removes the marker and cleans instance-specific state.
Physical Proxmox hosts are outside this handoff.

## Credential lifetime

`platform_credentials` uses the bootstrap file only in bootstrap mode. In
operational mode it reads Bao through HTTPS using the supplied token file and
fails on missing or denied secrets; it never falls back to `.env`.

Tailscale enrollment only runs when the node is not already `Running`. The
key is passed through a temporary root-owned `0600` file using the official
[`--auth-key=file:` interface](https://tailscale.com/docs/reference/tailscale-cli/up),
then deleted in an `always` block. The final backend state and online status
are mandatory. Existing node state is never deleted or reset.

`platform_credentials` with `tasks_from: seed` writes the declared external
credentials only when their current Bao value differs. Set
`platform_bootstrap_secrets` to entries with `path`, `field` and opaque local
`file`. Permitted destinations are the Tailscale enrollment and Hostinger API
paths; no existing unrelated fields are removed. Empty credentials are refused.

Generated Authentik secrets, the Bao static seal and recovery artifacts live in
protected persistent consumer state. Their recovery copies and independent SSH
break-glass access must exist outside Bao. A `.env` containing external tokens
alone cannot recover an existing vault. A missing cached Proxmox token fails
when the corresponding remote token still exists; it is never silently rotated.

## Firewalls and lockout protection

Proxmox uses its native firewall files. Guest VMs use a dedicated nftables
`milkyway` table and systemd unit; they do not replace or flush Docker or
Tailscale tables. The guest forward chain also blocks new LAN connections to
Docker-published ports. Outgoing traffic remains permitted. Tailscale encrypted
transport UDP 41641 is allowed; application access is exclusively through
`tailscale0`, subject to the existing tailnet policy.

The Proxmox rule list ends with an explicit DROP to prevent implicit LAN
management allowances from reopening SSH or port 8006. This initial role
refuses clustered hosts and refuses to overwrite firewall files it does not
own. Cluster communication requires a separately approved policy later.

Changed firewall policies arm a systemd rollback timer before activation.
Previous files are restored if automation loses access. Rollback is canceled
only after a fresh SSH connection succeeds. The SSH check disables connection
multiplexing and requires strict host-key checking. A new tailnet address is
associated with the public host key obtained through the already trusted
bootstrap transport, without trusting an unauthenticated network scan.

A restrictive firewall does not repair an overly broad shared tailnet ACL.
The consumer must verify that approved operators can reach management ports
and unauthorized tailnet identities cannot. Preserve Jarvis rules when making
that policy change.

## Scoped Proxmox identity

The API identity defaults to `nimbus@pve!provisioning`. VM privileges apply only
to the dedicated pool; storage privileges apply only to declared storage paths;
the node grants read-only audit access. No global administrator role is granted.
Templates and VMs provisioned with this identity must belong to that pool.
The token inherits its user ACLs (`privsep=0`); it is not an unrestricted root
identity. The token is written locally with `0600` and never displayed.

## Native host telemetry

`alloy_native` reuses the Jarvis Alloy configuration on the Proxmox host,
changing container `/rootfs` paths to native `/`, `/proc` and `/sys` paths.
It disables Docker collection and installs no Docker daemon. Grafana Alloy
1.18.0 for amd64 is downloaded from the official GitHub release and checked
against its pinned SHA-256 asset digest before extraction. A dedicated systemd
unit preserves its WAL, restricts writes to its state directory and exposes
readiness only on loopback. Configuration is validated before restart.

## Acceptance

- Repeat Ansible application has no unexpected configuration changes.
- Repeat OpenTofu plan has no resource changes.
- Reboot preserves tailnet identity and resumes the services and telemetry.
- A fresh authorized tailnet SSH session and Proxmox HTTPS request succeed.
- New LAN/public management connections fail after cutover.
- OIDC opens the dashboard and authenticated application sessions.
- An application's machine identity cannot read another namespace or sign SSH
  certificates.
- Bao and Authentik outage recovery remains possible with independent access.
- Lost local credential state aborts without rotation or deletion of live data.

Syntax checks and template rendering are prerequisites. They do not prove
firewall behavior, remote availability or authorization on the deployed hosts;
those require the consumer's approved live acceptance run.

## Live verification playbook

`verify.yml` takes explicit `platform_verify_urls` (URL, accepted status codes
and optional CA file), `platform_verify_oidc` (discovery URL and expected
issuer), `platform_prometheus_url`, `platform_loki_url`,
`platform_grafana_url`, `platform_authentik_url` and `env_name`. Every managed
host must retain its bootstrap `platform_lan_address` after switching SSH
transport to Tailscale. The checks use fresh connections rather than an
existing multiplexed SSH socket.

Verification checks trusted TLS, OIDC discovery and Grafana's unauthenticated
redirect to Authentik. It does not claim a completed interactive SSO login.
Prometheus host metrics and Loki numeric ingestion counts must include every
physical and virtual managed host; raw journal messages are never fetched by
the acceptance check. New management connections to the retained LAN address
must fail after lockdown.

Native firewall rule order is derived from the upstream
[Proxmox firewall compiler](https://github.com/proxmox/pve-firewall/blob/master/src/PVE/Firewall.pm):
explicit host rules precede implicit management IPSet allowances. Live negative
connection tests remain mandatory.

The provisioning identity receives guest-agent audit and pool audit inside its dedicated pool, plus `SDN.Use` only on declared `/sdn/zones/localnetwork/<bridge>` paths. Guest execution remains on the trusted bootstrap SSH transport; no unrestricted guest-agent execution permission is granted to the provider. These permissions were checked against Mercury's installed Proxmox9.2 source before live provisioning.

Bootstrap seeding explicitly reads `platform_bootstrap_bao_token_file`, independently of the operational token setting. Operational extra variables cannot override that selection. Once the external credentials are stored, normal service access uses the scoped operational identity.

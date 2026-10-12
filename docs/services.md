# Basic services

MilkyWay supplies reusable service definitions and Ansible roles. Nimbus selects
hosts, endpoints, exact image releases, credentials and OpenTofu state. Services
run in Linux guests; Docker is not installed on the Proxmox hypervisor.

## Modules and responsibilities

| Module | Responsibility | Main implementation |
| --- | --- | --- |
| Authentik | Identity provider and application dashboard | Standalone Compose with its own PostgreSQL; readiness includes required built-in blueprints |
| OpenBao | Secrets, machine identities and SSH signing | Standalone Compose with persistent Raft storage and static auto-unseal |
| Traefik | Private HTTPS and DNS-01 certificates | Tailnet listener, file-based routes, Hostinger API credentials |
| Observability | Grafana, Prometheus, Loki and Alertmanager | Provisioned dashboards, inventory alerts, private telemetry receivers |
| Alloy | Host, journal and container telemetry | Explicit metrics/logs destination URLs supplied by the deployment |
| Komodo | Container deployment management | MongoDB, Core and Periphery; private Core listener and Authentik OIDC |
| Docker engine | Guest container runtime | Official Docker packages and service enablement |

Tempo is outside this release. Application stacks, application-specific dashboards
and application-specific alerts are not included.

Compose definitions under `services/` are copied unchanged by Ansible. Runtime
configuration is rendered into protected files on the target. Changing that
configuration triggers a restart only when required; readiness checks follow
pending restarts. Existing image versions inherited from Jarvis remain explicit;
Komodo and MongoDB require exact release inputs rather than rolling defaults.

## Consumer inputs

The consumer provides these shared variables:

| Input | Meaning |
| --- | --- |
| `env_name` | Deployment label |
| `milkyway_services_dir` | Framework service directory; defaults relative to the role |
| `milkyway_secrets_dir` | Local protected generated credential directory |
| `milkyway_tofu_workdir` | Consumer OpenTofu workspace receiving bootstrap connection files |
| `platform_access_mode` | Explicit `bootstrap` or `operational` credential resolution |
| `platform_bao_addr` | Trusted HTTPS OpenBao endpoint |
| `platform_bao_token_file` | Protected local operational credential path |

`milkyway_secrets_dir` and `milkyway_tofu_workdir` also accept the shared
`platform_secret_files_dir` and `platform_tofu_workdir` aliases. Service-specific
inputs remain prefixed with the role name. Endpoints, addresses, routes, groups,
retention and image tags belong to the consumer inventory. Host names and domains
are not built into the framework.

Alloy takes `alloy_metrics_url` and `alloy_logs_url`. Komodo requires
`komodo_image_tag`, `komodo_mongo_tag`, `komodo_host_url` and its Bao OIDC secret.
Traefik takes an explicit Tailscale IPv4 address, routers, ACME account and
provider configuration. A router named `openbao` must block `/v1/sys/metrics`.

## Ordered startup

1. The consumer provisions guests and establishes restricted access.
2. Ansible installs the runtime and starts Authentik and OpenBao independently.
3. The DNS root manages only declared records. Traefik obtains certificates using
   DNS-01, without opening an Internet listener.
4. Ansible exports protected Authentik/Bao connection files into the consumer
   OpenTofu workspace. OpenTofu creates groups, infrastructure OIDC clients,
   vault engines, policies and machine identities.
5. Komodo and Grafana are deployed with complete OIDC configuration. Grafana
   readiness also verifies that its login delegates to the configured provider.
6. Alloy publishes logs and metrics to the declared private receivers.

The orchestration entry point belongs to Nimbus. There is no implicit deployment
on a MilkyWay release. A service health endpoint alone is not proof that a human
can complete an SSO login; the final deployment must test that flow separately.

## Credential and recovery behavior

Bootstrap may use an explicitly supplied `HOSTINGER_API_TOKEN` from the local
bootstrap environment. In operational mode Traefik ignores that environment
value and requires Bao. Komodo and optional alert delivery read Bao through HTTPS
using a local token file, with credentials excluded from automation output.

Generated Authentik credentials, Bao seal material and recovery artifacts are
persisted in the consumer's protected directory. Existing Authentik, Grafana and Komodo deployments
refuse to regenerate a missing credential cache. An existing vault refuses to
generate a new seal when data or an installed seal is present, and refuses to
overwrite an installed seal with a different cached key. Recovery requires the
original protected artifacts; Bao cannot be the only place they are stored.

OpenTofu state can contain client secrets. Encryption, locking, independent
recovery and provider authentication are consumer root responsibilities. Reusable
modules contain no backend, provider credentials or personal inventory.

## Application contract

Applications adapt to the infrastructure's OIDC claims/endpoints, TLS, Bao policy
boundaries and telemetry endpoints. Application registration adds metadata
(client, callback URLs, group access and dashboard entry) through generic
OpenTofu resources. It does not change Authentik's implementation or add an
application-specific branch to MilkyWay.

Human service access uses Authentik. Unattended services use their own scoped
machine identities; an interactive browser session is not a runtime dependency.
Local recovery accounts remain protected recovery mechanisms, not the ordinary
application login flow.

## Verification boundary

Source validation checks Ansible syntax, Compose configuration and provider
schemas. Isolated OpenBao tests exercise missing and mismatched seal safeguards
without starting a vault. Live acceptance still requires a fresh deployment,
repeat runs with no unexpected changes, reboot recovery, authorized tailnet
access, denied LAN/public access, a complete human SSO login and visible telemetry.

## Offline validation

`make infrastructure-check` runs provider-schema validation and mocked plans for all five OpenTofu modules, syntax checks for every Ansible playbook using synthetic inventory, YAML checks and four vault seal-preservation scenarios. It uses a locked infrastructure toolchain and explicit collection versions; it never reads deployment credentials or contacts the homelab. The protected `make check` gate includes it. Live convergence, network isolation and browser sign-in remain separate deployment evidence.

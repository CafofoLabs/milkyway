# Jarvis reuse audit

Source: Jarvis checkout at commit `068e24ba03ff4eed0004b6b534b135112c81b1e9`.
Only tracked Compose/HCL, role YAML/Jinja/dashboard source and generic OpenTofu
modules were selected. No inventory, `.env`, secret cache, key, state or backend
configuration was copied.

| Source | Reuse result |
| --- | --- |
| `services/authentik`, `services/openbao`, `services/traefik`, `services/observability`, `services/alloy` | Runtime topology retained; source comments adjusted to the new documentation layout |
| `services/komodo` and duplicated role Compose | Single Compose source; loopback Core binding, existing-credential guard and required exact image tags |
| `ansible/roles/authentik` | Blueprint readiness retained; stable consumer paths; missing-cache safety |
| `ansible/roles/openbao` | Static seal, initialize-once, cached recovery retained; existing-data/mismatched-key safeguards added |
| `ansible/roles/traefik` | DNS-01 and route checks retained; explicit bootstrap/operational resolution and production trust verification |
| `ansible/roles/observability` | Basic telemetry stack retained; mandatory Grafana OIDC and existing-credential guard; application alert/dashboard rules omitted |
| `ansible/roles/alloy`, `docker_engine` | Guest runtime/collection retained; explicit telemetry destination inputs |
| `tofu/modules/authentik-baseline` | Generic provider/application/group/dashboard resources retained |
| `tofu/modules/openbao-baseline` | Generic engines, policies, OIDC, machine identity and SSH CA retained |
| `tofu/dns` | Resource logic extracted as `hostinger-dns`; personal defaults, backend and provider credential configuration omitted |

The reusable roles accept consumer-owned paths and inputs. The basic services
remain integrated; there is no unnecessary split of their identity graph.
Application declarations from the old environment root were not migrated.

## Checks

- Owned YAML files parsed with PyYAML.
- Six standalone Compose definitions validated with `docker compose config
  --quiet --no-env-resolution` using synthetic inputs and no Docker daemon.
- `tofu init -backend=false` and `tofu validate` passed for Authentik, OpenBao and
  Hostinger DNS modules in temporary directories using declared provider schemas.
- OpenBao guard tests run the actual Ansible guard tasks against temporary files:
  new vault allowed; missing cached seal rejected; mismatched seal rejected;
  matching seal accepted. Run with `python -m unittest discover -s
  ansible/roles/openbao/tests` in the tooling environment.

These are source and isolated safety checks. They do not prove live deployment,
full SSO, firewall isolation, reboot recovery or a drift-free second apply.
Jarvis resources were not modified.

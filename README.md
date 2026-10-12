<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/milkyway-dark.png">
  <img src="docs/assets/milkyway-light.png" alt="MilkyWay orbital terminal logo" width="720">
</picture>

# MilkyWay

A framework for provisioning and configuring a professional self-hosted homelab, built around Proxmox, Tailscale, Authentik, OpenBao, Komodo, and observability.

**Status:** repository safeguards, Proxmox baseline, private Tailscale access, DNS/TLS, and basic service modules are implemented. Consumers deploy through their own inventory and OpenTofu state. Backup/recovery automation and fine-grained telemetry network policy remain separate work.

Run `make setup` to install development tools and hooks, then `make check`. See [development](docs/development.md) and [releases](docs/releases.md).

- [Foundation plan](docs/foundation-plan.md)
- [Brand assets](docs/branding.md)

[Basic services](docs/services.md) · [Application contracts](docs/application-contracts.md)

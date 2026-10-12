# Observability and telemetry access

## Purpose and modules

The `observability` role deploys Grafana, Prometheus, Loki and Alertmanager on a consumer-selected guest. The `alloy` role sends host, journal and container telemetry from selected machines. Tempo is excluded. See [services](services.md) for the deployment dependency order.

## Inputs, outputs and execution

The consumer provides service versions, Grafana URL/OIDC configuration, the Tailscale bind address, retention settings, inventory and `alloy_metrics_url` / `alloy_logs_url`. The output is a Grafana dashboard plus private telemetry APIs. The consumer's Makefile orchestrates Ansible; the framework's `make infrastructure-check` validates definitions without contacting hosts.

Grafana delegates human login to Authentik. Grafana, Alertmanager and local exporters use loopback or container networks. Prometheus TCP 9090 and Loki TCP 3100 are published on the selected Tailscale address so remote Alloy agents can send data. Current remote telemetry URLs use HTTP inside the encrypted Tailscale connection; these APIs do not have application-level authentication.

## Permissions and current boundary

Joining the tailnet does not grant an Authentik session, but access to the telemetry ports is a separate network permission. A device allowed to reach those ports by the tailnet policy can access APIs directly, bypassing Grafana's login. Loki's `auth_enabled: false` selects a single tenant; changing it to `true` alone does not authenticate callers. [Loki authentication](https://grafana.com/docs/loki/latest/operations/authentication/) requires a separate authentication layer when one is needed.

Guest firewalls deny new LAN access and allow traffic arriving through `tailscale0`. They do not currently distinguish telemetry clients. Tailnet policy is external to these roles. A private bind address is not proof that only approved telemetry clients can reach it.

The next network-policy increment should allow inventoried agents to reach the receiver ports and deny unrelated devices. Grafana queries locally. Port rules restrict machines, not HTTP operations: separate write-only ingestion routes would require an additional proxy/authentication contract. Prometheus's lifecycle API is also enabled in the current service definition; assess whether it is needed before permitting additional clients. See the [Prometheus security model](https://prometheus.io/docs/operating/security/).

## Repeated runs and verification

Ansible reconciles Compose, configuration, dashboards and inventory alerts. Configuration changes restart affected services; repeated unchanged runs preserve data volumes. Acceptance requires numeric checks proving metrics and log ingestion for each expected host, a human Grafana login, denied LAN access, and policy tests from both allowed and denied tailnet identities. Positive ingestion alone does not prove access isolation.

## Recovery and remaining work

Metrics/log retention settings are not backups. Persistent volumes survive normal reconciliation, but recovery after disk loss needs separately implemented backup and restore procedures. Do not delete volumes to repair a configuration failure. Preserve configuration and data, fix the declared inputs, then rerun the consumer's approved deployment flow.

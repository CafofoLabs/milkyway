# Native Proxmox TLS

`proxmox_tls` issues a certificate for the declared node FQDN using Let's
Encrypt DNS-01 and Hostinger. It installs Lego directly on Proxmox; it does
not install Docker, start a public listener, or open an inbound firewall port.
Private DNS registration precedes this playbook; validated Proxmox HTTPS
precedes OpenTofu VM provisioning.

## Inputs and execution

The consumer supplies `proxmox_tls_fqdn`, `acme_email`, and
`acme_dns_resolvers` (comma-separated recursive resolvers with `:53`, for example
`1.1.1.1:53,1.0.0.1:53`).
`acme_ca_server` selects `production` or `staging`; production is the default.
Authoritative-only zone servers do not provide the recursive lookups needed
for parent-zone discovery and CNAME resolution. Lego discovers authoritative
servers itself; both recursive and authoritative checks remain enabled. The playbook is `ansible/playbooks/proxmox-tls.yml`, using
the consumer's existing inventory and private variable files. Nimbus exposes
this through `make host-tls` and its complete host setup command.

Lego is pinned to v5.5.2 and its official Linux amd64 archive SHA256:
`2a35505089e7772c92e1e9ac144df91151ef2eca8568630db0ff91fca06d9bef`.
The role checks the declared platform, downloads and verifies the archive,
installs it under `/opt/milkyway/lego/5.5.2`, and retains ACME state under
`/var/lib/milkyway/proxmox-tls/<production|staging>` with root-only access.
Changing the CA selects separate state; it never deletes another CA's account
or certificates. A staging execution tests issuance only: it never installs
an untrusted certificate into Proxmox and disables the production renewal
timer until production configuration is reapplied.

## Credentials and ownership

Credential resolution reuses `platform_credentials`:

- Explicit bootstrap mode reads `platform_hostinger_key_file`, an opaque
  file materialized from the consumer's local `.env` by its existing wrapper.
- Operational mode reads only Bao path `platform/hostinger/api`, field `token`,
  using `platform_bao_addr` and `platform_bao_token_file`. Bao failure stops
  reconfiguration; the role does not fall back to bootstrap credentials.
- The resolved value is copied with `no_log`, no diff, and mode `0600` to
  `/etc/milkyway/proxmox-tls/hostinger_api_token`. Temporary Ansible facts are
  then cleared. The containing directory has mode `0700`.
- Systemd `LoadCredential` provides the runtime file. Lego receives only its
  path through `HOSTINGER_API_TOKEN_FILE`; no secret appears in arguments,
  unit files, automation output, or reconciliation logs. Third-party command
  output is captured in memory only and discarded after selecting a fixed
  failure label; HTTP error payloads are never written or logged.

The local runtime copy is deliberate: renewal must survive Bao downtime and
must work while Bao itself is being created. Operational reconfiguration
refreshes this copy from Bao; it does not query Bao during the timer run.
Rotate the Hostinger token in Bao, reapply this role, and revoke the old token
after confirming renewal uses the replacement. Hostinger's API token is
account-wide; file permissions do not provide narrower API authorization.

## Idempotence and recovery

The root-only helper `/usr/local/libexec/milkyway-proxmox-tls` takes a local
`flock`, then runs Lego's v5 `run` command. This command obtains a missing
certificate and checks renewal for an existing one using ARI and lifetime-aware
renewal timing. It never forces renewal merely because configuration is applied
again. Both authoritative and recursive propagation checks remain enabled.
The Hostinger propagation timeout defaults to 1200 seconds, allowing a zone
negative-cache TTL of 600 seconds to expire. The systemd service deadline is
3600 seconds to also allow renewal jitter and certificate verification.

Before installation, OpenSSL verifies the certificate chain, server purpose,
hostname, and matching public key. If the installed certificate and the
certificate served on loopback already match, the helper exits successfully
without restarting Proxmox. Otherwise it calls:

```text
pvenode cert set CERTIFICATE_FILE PRIVATE_KEY_FILE --force 1 --restart 1
```

The CLI loads the file contents internally. Proxmox validates the pair and
restores the previous custom pair when installation fails. The helper then
checks that port 8006 serves the expected trusted certificate. A failed
installation or proxy reload is retried on the next run using the saved
certificate; it does not require another issuance. Issuance failure leaves
the installed certificate unchanged. Public HTTPS is also validated from the
control node with certificate checks enabled and without an HTTP proxy.

`milkyway-proxmox-tls.timer` runs daily with a randomized delay. Its service
has no Bao dependency. The local lock prevents concurrent manual and timer
runs on one node; it is not a distributed DNS lock. Initial playbook runs are
serialized. Mercury and service certificates must use distinct names, and
multiple issuers must not concurrently manage the same TXT record set.

Check `systemctl status milkyway-proxmox-tls.service` and
`systemctl list-timers milkyway-proxmox-tls.timer` for sanitized status. The
helper invokes Lego with error-level text logging, so routine propagation INFO
messages cannot mask the final error. Its only emitted diagnostics are fixed
labels: `acme-rate-limit`, `acme-invalid-contact`, `acme-unauthorized`,
`acme-caa`, `acme-dns`, `acme-rejected`, `dns-provider-auth`,
`dns-provider-update`, `zone-discovery`, `propagation-timeout`, `network`,
`dns-propagation`, or `unknown`. Specific ACME problem types take precedence
over generic provider or DNS wording. Classification is diagnostic guidance,
not proof of the provider's root cause. Raw provider output is never persisted.
A failed timer leaves the current certificate in service; fix the reported
condition before the certificate expires, then rerun the consumer command.
Recovery from lost ACME state can require fresh issuance and consume CA limits.

## Verification

`make infrastructure-check` checks the playbook syntax and runs disposable
TLS reconciliation fixtures. Fixtures exercise unchanged certificates,
installation recovery, invalid chains/hostnames/keys, failed issuance, private
credential paths, and staging isolation. They do not contact Hostinger, issue
public certificates, connect to Mercury, or prove a live renewal.

After deployment, acceptance requires trusted access to the private FQDN,
a successful OpenTofu provider connection with TLS verification enabled,
a healthy enabled renewal timer, and a repeated apply without certificate
replacement. DNS-01 only needs outbound DNS/HTTPS connectivity. Public
certificate issuance records the requested name in Certificate Transparency;
it does not publish the service itself.

## Sources and reuse

This role reuses Jarvis's Traefik DNS-01 approach and MilkyWay's explicit
bootstrap/Bao credential contract. Resolver configuration corrects Jarvis's
authoritative-only assumption: the Lego option requires recursive resolvers.
The dedicated native installation replaces the Docker assumption on hypervisors.

- [Pinned Lego release](https://github.com/go-acme/lego/releases/tag/v5.5.2)
- [Hostinger provider and file-based credentials](https://go-acme.github.io/lego/dns/hostinger/)
- [Lego recursive-resolver option](https://github.com/go-acme/lego/blob/v5.5.2/cmd/internal/flags/flags.go)
- [Lego propagation checks](https://github.com/go-acme/lego/blob/v5.5.2/challenge/dns01/dns_challenge_precheck.go)
- [Lego v5 issuance and renewal](https://github.com/go-acme/lego/blob/v5.5.2/cmd/cmd_run.go)
- [Let's Encrypt DNS-01](https://letsencrypt.org/docs/challenge-types/#dns-01-challenge)

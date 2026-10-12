# Application access contract

Applications adapt to MilkyWay's existing infrastructure. They implement standard OIDC, consume their own OpenBao namespace and manage their own deployment. Onboarding does not change the Authentik server configuration, OpenBao baseline or MilkyWay source for each application.

The reusable `tofu/modules/application-access` module registers an application through existing service APIs. Its state belongs to that application, separately from Nimbus's infrastructure state. The module reuses Jarvis's OAuth2 provider, signing key/flow lookups and AppRole patterns, without taking ownership of shared groups, authentication backends or secret mounts.

## Prerequisites and responsibilities

The infrastructure supplies running HTTPS Authentik/OpenBao endpoints, existing identity groups, Authentik's standard OIDC scopes and flows, an asymmetric signing key, a KV v2 mount and the `approle` auth backend. Network access remains private through Tailscale.

The application's deployment supplies its private HTTPS address, exact callback route, standard confidential OIDC client implementation and a private server-side credential store. It validates issuer, audience, signature, state and nonce using a maintained OIDC library; browser login uses authorization code with PKCE. Its machine process logs into OpenBao with its own AppRole and obtains short-lived tokens without a human login. It renews or obtains another token as needed; it never holds infrastructure provisioning tokens.

This first contract supports server-side confidential web applications. It does not add a login proxy or adapt the infrastructure to an application's custom authentication behavior. Public/browser-only clients, machine-to-machine OAuth flows, application deployment, VM provisioning, DNS records and network publication are separate contracts.

## Inputs and managed resources

| Input | Contract |
| --- | --- |
| `slug` | Unique lowercase application name; fixes the secret prefix to `apps/<slug>`. |
| `name`, `launch_url` | Dashboard label and private HTTPS destination. |
| `identity_url` | Existing Authentik HTTPS origin without trailing slash. |
| `redirect_uris` | Exact HTTPS authorization callbacks; no wildcard matching or fragments. |
| `access_group_ids` | One or more existing group UUIDs allowed to access the app. |
| `vault_mount` | Existing KV v2 mount, default `secret`. |
| Signing key and flow inputs | Defaults match the baseline; use the infrastructure's published choices when customized. |

The module creates one OAuth2 provider, one Authentik application, its existing-group bindings, one OpenBao policy, one AppRole and one SecretID. Authentik shows the app in the dashboard for permitted groups and performs their login. It does not create groups, users, secret values, secret mounts, global policies or auth backends. Removing an app must never remove those shared resources.

## Secret isolation and credential delivery

The AppRole can read/list only its own `apps/<slug>` KV v2 namespace. It cannot read another app or `platform/`, write/delete secrets, sign SSH certificates or administer OpenBao. Its token has no inherited default policy; explicit self-token lookup, renewal and revocation permissions support normal client operation. Tokens start with a one-hour TTL and have a four-hour maximum lifetime. The SecretID is durable to support unattended restarts; rotate or revoke it explicitly when required.

`oidc_endpoints`, `secret_prefix` and `secret_policy` are non-secret metadata. `oidc_client` and `approle_credentials` are sensitive outputs. The deployment automation must consume them directly into the application's protected secret storage without displaying them. Sensitivity redacts ordinary OpenTofu output; it does not remove credentials from state or make JSON output safe to print. State and saved plans require enforced encryption, restrictive local permissions and recovery material outside OpenBao.

Provisioning API credentials are separate from application runtime credentials. Only trusted deployment automation receives the permissions to register providers/applications and app policies/AppRoles. The runtime AppRole cannot run this provisioning module. Token scope and who may run the deployment remain infrastructure policy decisions.

## Example and execution

`examples/application/` is a separate application consumer root using the same local module source for this checkout. A real application repository pins an accepted MilkyWay release/commit instead. Copy the non-secret example inputs to local `terraform.tfvars`, supply existing group UUIDs and actual private URLs, and supply `TF_VAR_authentik_api_token`, `VAULT_TOKEN` and `TF_VAR_state_encryption_passphrase` through the trusted execution environment. Never put their values into tracked files or command arguments.

The example's Makefile runs `make plan` to initialize its own encrypted local state and save an encrypted plan, then `make apply` to execute that reviewed plan. Commit the consumer root's generated provider lock. Its backend does not import Nimbus state or depend on the OpenBao it describes. Do not run simultaneous state-changing operations against the same root; share the encrypted state and recovery material deliberately before moving control nodes.

After apply, the application's deployment consumes the two sensitive credential outputs programmatically and configures its own OIDC and OpenBao clients. The module does not start an application process or populate its secrets. Repeating a plan should preserve existing clients and SecretIDs and show no changes absent drift. Changing its slug changes ownership identifiers and must be reviewed as an application migration. Destroying its consumer resources revokes that app's login/machine identity; existing secret data is intentionally outside this module's ownership.

## Verification

Offline mock-provider tests verify the standard contract, distinct issuers and secret policies for two apps, and rejection of path injection and unrestricted identity access. They do not prove a real browser login or an OpenBao enforcement decision.

Live acceptance uses two disposable app consumers: each reads a synthetic secret in its own namespace, receives denial for the other's namespace, and has no SSH/platform capability. A standard OIDC client must complete login for an allowed user and deny a user outside the configured groups. A repeat plan must show no changes, and removing one consumer must preserve the other app and all baseline resources. Browser login remains a separate acceptance check until it is actually exercised.

## Sources

- [Authentik OAuth2 provider schema](https://github.com/goauthentik/terraform-provider-authentik/blob/main/docs/resources/provider_oauth2.md)
- [Authentik application and dashboard metadata](https://github.com/goauthentik/terraform-provider-authentik/blob/main/docs/resources/application.md)
- [OpenBao AppRole authentication](https://openbao.org/docs/auth/approle/)
- [OpenBao KV v2 API](https://openbao.org/api-docs/secret/kv/kv-v2/)

# Application service identities

MilkyWay owns the versioned YAML contract, authorization validation, native
OpenTofu modules, execution and reference runtime client. Consumers supply a
trusted deployment catalog and an application manifest. Nimbus is one consumer;
no Nimbus service or operator is required when an application authenticates.

## Contract and trust boundary

The v1 contract is described by `contracts/application-identity-v1.schema.json`.
The executable validator additionally checks account uniqueness, registration,
namespace ownership and requested grants against the catalog. Unknown fields,
duplicate YAML keys, wildcard/traversal paths and unsupported database blocks
are errors. An empty account list explicitly plans removal of all owned accounts.

```yaml
version: 1
application: inventory
environment: dev
serviceAccounts:
  - name: svc-inventory-dev
    enabled: true
    credentialRevision: 1
    roles: [application-service]
    secrets:
      read:
        - mount: secret
          path: apps/inventory/dev
          recursive: true
        - mount: secret
          path: shared/mail
```

`enabled` defaults to true, `credentialRevision` to 1 and `recursive` to false.
Each account name must be `svc-<application>-<environment>` or start with that
prefix followed by a hyphen. Account names are globally unique within Authentik;
register each application/environment once per IdP. The catalog rejects pairs
whose concatenated namespace would collide. Account names that overlap another
registered namespace are rejected too.

`read` grants only KV v2 data reads. It does not allow listing, metadata reads,
writes, deletes or access to another prefix. Recursive permission includes the
exact path and its descendants, with a slash boundary. A requested recursive
read requires a recursive platform grant. Duplicate accounts and rules are errors.

The platform-owned catalog defines deployment name, HTTPS origins, existing
asymmetric RSA signing key and authorization/invalidation flows, dedicated JWT
mount, JWT/Bao TTLs, logical access profiles and the roles/paths allowed for each
application/environment. See `examples/service-accounts/catalog.yaml`.

Profiles map logical names to existing OpenBao policies and app-owned Authentik
groups. The catalog is an administrative input, never an application-supplied
file. Existing profile policies must be narrowly scoped read-only policies:
`verify` checks that declared secret paths have no write/list/metadata access
and probes unrelated application/infrastructure paths. These probes are not an
exhaustive audit of arbitrary externally maintained profile policies. Reserved
`root` and `default` policies are rejected. No IdP
administrative RBAC roles or shared baseline group memberships are assigned.
Changing an allowlist alone does not revoke existing resources: plan and apply
every affected application manifest. Keep manifests and catalogs under review.

## Native resources and ownership

`tofu/modules/machine-identity` owns one Authentik M2M provider/application,
service-only expression policy, stable-principal scope mapping and a separate
OpenBao JWT backend. It does not modify human OIDC, AppRole, KV mounts or shared
groups. The provider enables only `client_credentials`, uses the selected RSA
signing key and emits `service_account_id` from the immutable Authentik user PK.
Its policy admits only named service accounts under this deployment's path.
The JWT backend validates the exact issuer, JWKS and RS256 signatures.

`tofu/modules/service-account-access` owns named Authentik service users,
profile groups scoped to this deployment/application/environment, individual
app-password tokens, Bao entities/aliases, read policies and JWT login roles.
Each group exclusively owns its membership list; the user's computed group
membership and shared groups are not managed. Group names include a namespace
hash to fit IdP limits. Bao roles additionally bind audience, account PK,
application and environment and omit the default policy. Entities allow audit
correlation and explicit disabling; permissions stay on the login roles.

Foundation and every application/environment use independent encrypted native
states. There is no custom reconciliation database. Provider credentials need
administrative access to these resources; protect the provisioning runner and
restrict its network reach. Application YAML alone never selects provider
endpoints, arbitrary policies or platform allowlists.

## Execution

Use OpenTofu 1.12.6 and the locked Python environment. Provision the existing
KV v2 mount, IdP flows and RSA signing key first. The provider version line is
2026.5, matching the platform's Authentik line. Supply trusted automation with
`TF_VAR_authentik_api_token`, `VAULT_TOKEN` and
`TF_VAR_state_encryption_passphrase` through protected environment injection.
Keep encryption recovery material outside OpenBao. Do not put values on command
lines, in YAML, in Git or in console output.

```sh
make identity-validate MANIFEST=/absolute/path/application.yaml IDENTITY_CATALOG=/absolute/path/catalog.yaml
make identity-plan IDENTITY_COMPONENT=foundation IDENTITY_CATALOG=/absolute/path/catalog.yaml
make identity-apply IDENTITY_COMPONENT=foundation IDENTITY_CATALOG=/absolute/path/catalog.yaml
make identity-verify IDENTITY_COMPONENT=foundation IDENTITY_CATALOG=/absolute/path/catalog.yaml
make identity-plan MANIFEST=/absolute/path/application.yaml IDENTITY_CATALOG=/absolute/path/catalog.yaml
make identity-apply MANIFEST=/absolute/path/application.yaml IDENTITY_CATALOG=/absolute/path/catalog.yaml
make identity-verify MANIFEST=/absolute/path/application.yaml IDENTITY_CATALOG=/absolute/path/catalog.yaml
```

Alternatively invoke `scripts/service_identity.py` through
`uv run --frozen --project tools/infrastructure python`, with the same
`validate|plan|apply|verify`, `--catalog`, `--manifest`, `--component` and
`--workspace` arguments. This interface works without Nimbus. Workspace defaults
in Make to the ignored `.milkyway/identities`; use a persistent private location
in automation, never an ephemeral CI job directory without state recovery.

`plan` initializes and validates a generated native root, saves an encrypted
plan and prints only resource addresses/actions. Deletions and replacements are
visible there and require review of the manifest change. `apply` accepts only
that saved plan, checking its hash plus effective inputs, root and module source;
changes require a new plan. It never silently replans. A per-state lock prevents
concurrent operations. Apply produces a mode-0600 `deployment.json` under
`<workspace>/<deployment>/applications/<app>/<environment>/`. Deploy automation
must mount/copy this file privately into the selected workload. No new Komodo
integration or application deployment is introduced in v1.

The deployment file contains each enabled account's username, individual app
password and Bao role, plus non-secret connection metadata. Native state and
plans contain credentials and are encrypted; deployment files are plaintext
secrets and require protected storage, backups and transport. Provider output
and debug tracing are suppressed to avoid leaking credentials. Runbook failures
report the phase, not the provider's response body.

## Runtime and lifecycle

The application requests a signed access JWT from Authentik using its username
and app password, `grant_type=client_credentials`, this deployment's client ID
and `scope=milkyway-service`. It exchanges that JWT at
`auth/<authMount>/login` with its assigned Bao role. It then uses the short-lived
Bao token to read its secrets. Use a standard HTTP/OpenBao library or
`scripts/service_identity_runtime.py --credentials ... --account ... --output ...`.
The reference client writes a private session file and refuses redirects or
unprotected credential files. It never prints a token. Applications must renew
before the lease expires and reauthenticate by the explicit maximum TTL; the
reference executable performs one login and can be invoked again as needed.

An unchanged native plan preserves accounts and credentials. Increase
`credentialRevision` to force replacement of the app password; deliver the new
file and restart/reload the consumer. Rotation has no overlap window. Disable an
account by setting `enabled: false`: its IdP login is disabled, app password and
Bao JWT role removed, entity disabled and owned secret policy emptied. Existing
JWTs remain signed until expiry; removing the role prevents a new Bao exchange
through that role. Already issued Bao tokens are bounded by explicit maximum
TTL. Do not claim instant global session revocation; urgent incidents additionally
require native token revocation and application session termination.

Removing or renaming an account is an explicit native destroy/create plan.
A partial apply retains native state and the saved plan. If native state advanced,
OpenTofu rejects the stale plan: inspect the state through protected automation,
create/review a new plan and apply again. A failed credential delivery can be
recovered the same way, without regenerating an unchanged credential. Keep state
and its encryption key to recover stable identities; losing both is not a
stateless recreation of the same accounts. Never delete the foundation state
while applications depend on its JWT mount.

## Verification and limits

`verify` requires an applied matching contract, checks native no-change
convergence and performs real machine authentication for every enabled account.
It checks effective capabilities for exact and descendant read paths, denies
metadata/list/write and probes unrelated application and platform paths. The
verification token is revoked afterward. Permissions are checked without writing
or requiring that each secret already contain data. Foundation verification
checks convergence; an application verification is needed to prove the full flow.

`make check` includes strict parser/authorization tests, saved-plan binding and
failure recovery tests, reference-client protocol tests, native provider schema
validation and mocked lifecycle tests. Mocked tests establish configuration
behavior, not proof that deployed Authentik issues the expected JWT. Before
production use, run the real verifier with two isolated applications, reject
wrong issuer/audience/principal and expired JWTs, confirm unchanged plans and
exercise rotation/disable. Such live checks require a provisioned test environment
and are not performed automatically by credential-free CI.

PostgreSQL user synchronization, application database RBAC, LDAP, VM enrollment
and application deployment are outside v1. Database blocks fail validation rather
than appearing configured. The existing web application OIDC/AppRole contract
continues independently; see [Application contracts](application-contracts.md).

Protocol references: [Authentik M2M](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/machine_to_machine/),
[OpenBao JWT authentication](https://openbao.org/docs/auth/jwt/),
[KV v2 policies](https://openbao.org/docs/secrets/kv/kv-v2/).

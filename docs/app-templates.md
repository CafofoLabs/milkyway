# Application template library

The versioned `app-templates/` library supplies reusable application definitions.
Consumers own instance maps, worker placement, credential references and Komodo
reconciliation. Consume the accepted MilkyWay release, never a moving branch.

`scripts/mapped_apps.py` validates all maps before returning deployment input.
Explicit references are `milkyway/<name>` or `local/<name>`. Both use the same
contract. Duplicate names, Tailscale hostnames, worker loopback ports, YAML keys
and unknown fields are errors. Removing a map never destroys an instance.

## PostgreSQL 18

```yaml
version: 1
name: example-db
template: milkyway/postgres-18
parameters:
  user: thiago
  dba: true
  extensions: []
tailscale:
  hostname: example-db
  ephemeral: false
```

The default worker is `ganymede`. `local_port` defaults to the template's port;
override it for a second instance on the same worker. Each instance gets its own
Compose project, password, data volume and Tailscale identity. Images are pinned
by digest. This template initializes its declared user as a superuser;
`dba: false` is rejected. Only standard PostgreSQL databases are created.

An empty extension list adds nothing. Requested extensions are installed in
`postgres` after startup; their packages must already exist in the image.
Unavailable extensions fail explicitly. Removing an extension does not drop it.
Existing initialization settings are not silently rewritten.

Passwords are generated directly into protected worker files and preserved.
An existing data volume without its password file is an error. PostgreSQL 18
data is mounted at `/var/lib/postgresql`.

## Common platform behavior

The renderer adds an official Tailscale container using userspace networking
and a native Serve TCP forwarder to the application over the project network.
Its own tailnet identity exposes the service port. The application publishes a
loopback-only worker port and remains locally available across sidecar restarts.
Containers on the shared development network can use the instance name.
No host TUN device or extra network capability is required. PostgreSQL sees the
proxy's address for tailnet connections; the wire protocol is forwarded unchanged.

`TS_AUTHKEY=file:/run/secrets/tailscale_auth_key` keeps enrollment values outside
Compose and the Periphery-visible directory. Persistent identities use a named
state volume. Ephemeral identities use in-memory state and the consumer's
ephemeral enrollment key. Application data persistence is independent.
Changing an existing template or Tailscale identity requires explicit migration.
Enrollment keys must be reusable and pre-approved when device approval is enabled.
Otherwise a new device waits for a tailnet administrator in `NeedsMachineAuth`.
Applications start locally while enrollment is pending; end-to-end verification
still requires the Tailscale container to become healthy.

Every service emits rotated Docker JSON logs. A required worker Alloy collector
discovers all containers and forwards stdout/stderr to Loki with `host`, `stack`
and `service` labels. Apps that log only to private files must also emit stdout
or stderr; Docker cannot collect those files.

## Remote MCP

The [FastMCP proxy](fastmcp-proxy.md) uses the same mapping lifecycle, with a
pinned Bao configuration reference and one scoped workload identity per instance.
It exposes HTTPS on tailnet port 443 through Tailscale Serve instead of raw TCP.

## Adding templates

Create `app-templates/<name>/template.yaml` and `compose.yaml.j2`. The descriptor
contains `version: 1`, `name`, `primary_service`, `port`, `parameters`, and optional
`hooks`, `files`, `runtime_config` and `tailscale_https`. `files` lists immediate
template assets staged alongside hooks. A runtime-config template requires
`config_ref` and `identity` in its instance map and catalog authorization.
Parameter types are `string`, `boolean`, `integer`, and `array`, with
`default`, `enum`, `pattern`, and `item_pattern` validation. Parameters without a
default are required. Jinja receives `name`, `worker`, and `parameters`.

The primary service requires a healthcheck. The platform owns its networking,
the `tailscale` service, `tailscale_state` volume and `development` network.
Template files and directories cannot be symlinks. Optional `prepare`,
`configure`, `verify`, and `verify_client` hooks name Python files in the template directory.
They receive `MAPPED_APP_NAME`, `MAPPED_APP_WORKER`, and JSON
`MAPPED_APP_PARAMETERS` on the worker. Preparation and configuration print
`changed=true` only when state changes. Verification must not modify the app.
Hooks are trusted IaC and must never return credential values.
The optional client hook runs on the control node with `MAPPED_APP_PARAMETERS`,
`MAPPED_APP_TAILSCALE_IP`, `MAPPED_APP_TAILSCALE_DNS` and `MAPPED_APP_PORT`. PostgreSQL uses it to require a
real SCRAM authentication challenge through the full tailnet TCP forwarding path.
`immutable_parameters` lists initialization parameters that cannot change on an
existing instance. PostgreSQL uses this for its user and DBA setting.

Template updates require library tests, Compose validation and normal release
checks before a consumer updates its pin.


## Service references and prebuilt runtime images

Runtime maps may use an immutable prebuilt image without a build section. Build
suffixes and the `build` pull policy apply only to services that actually build.
Pinned configuration/credential revisions are also exposed as `APP_CONFIG_VERSION`
and `APP_CREDENTIAL_REVISION`; existing MCP variables remain compatible.

`identity.read` optionally declares additional Bao KV read rules using the same
`mount`, `path` and optional `recursive` contract as service-account manifests.
These rules are included in the scoped account manifest and must pass the trusted
consumer catalog. This supports a server configuration referring to separate DB,
Loki and S3 documents without granting an entire application subtree. Omitting
`read` preserves the existing single-document permission. Never declare bootstrap
administrator references on a runtime account.

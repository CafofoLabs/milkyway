# Remote MCP proxy

`milkyway/fastmcp-proxy` runs FastMCP 4.1.0 in a non-root, read-only container.
It proxies one remote Streamable HTTP MCP endpoint. Dependencies are locked and
hash-checked; Komodo builds from the accepted template's staged files. The
container receives only its scoped machine identity. It authenticates to OpenBao,
reads one pinned KV v2 version into memory, and revokes the short-lived Bao token.
Bundle values never enter Compose, image layers, command arguments or telemetry.

## Instance declaration

```yaml
version: 1
name: mcp-atlassian-human
template: milkyway/fastmcp-proxy
worker: ganymede
local_port: 8101
config_ref:
  mount: secret
  path: apps/mcp/human/atlassian
  version: 1
identity:
  application: mcp-human
  environment: prod
  account: svc-mcp-human-prod
  credential_revision: 1
tailscale:
  hostname: mcp-atlassian-human
```

The consumer catalog must authorize the exact bundle path. Placement, ports,
identity and the reviewed bundle version stay in YAML. `hostname` in Bao must
match the declared Tailscale hostname; changing a secret cannot rename or relocate
an instance. The mapping provides public references, not workload secrets.

## OpenBao KV v2 fields

Create the following fields directly in the Bao UI or through your protected
secret-management workflow. Do not paste values into chat or shell arguments.
Structured fields accept JSON objects/arrays, or strings containing valid JSON
for UI forms that only support text.

| Field | Required value |
| --- | --- |
| `hostname` | Exact declared Tailscale hostname |
| `upstream_url` | Full HTTPS MCP URL, without credentials, query or fragment |
| `auth_type` | `basic`, `bearer`, `headers` or `none` |
| `clients` | JSON object mapping agent names to independent random bearer tokens; at least 32 characters per token |
| `allowed_tools` | Nonempty JSON array of exact upstream tool names |
| `cloud_id` | One Atlassian Cloud ID; required for `mcp.atlassian.com`, omitted for other MCPs |
| `allowed_origins` | Optional JSON array of exact HTTPS browser origins; default is empty |

Authentication fields are exclusive:

| `auth_type` | Additional fields |
| --- | --- |
| `basic` | `email`, `api_key` |
| `bearer` | `api_key` only |
| `headers` | `headers`: JSON object of fixed upstream header names/values |
| `none` | No authentication fields |

The upstream URL includes its hostname; no separate upstream host is needed.
The instance's client tokens must be different from its upstream API key and
from tokens registered for other companies. They authorize only this proxy.

## Enforcement and access

Clients connect to `https://<hostname>.<tailnet>.ts.net/mcp` with
`Authorization: Bearer <their-proxy-token>`. Tailscale Serve provides TLS and
tailnet-only access; Funnel is disabled. The worker binds internal HTTP only to
loopback. HTTPS must already be enabled for the tailnet. Tailscale grants should
allow only authorized agent nodes to reach the instance's TCP 443.

Every tool call is checked against the exact allowlist. With `cloud_id`, tools
without a `cloudId` schema field are hidden and calls must provide that exact
value. This does not restrict Jira projects or Confluence spaces inside the
allowed site; apply account permissions for those boundaries. Resources, prompts,
tasks, roots, sampling and elicitation forwarding are disabled. Caller headers
are never forwarded upstream, TLS verification remains enabled, and redirects
and environment HTTP proxies are refused. No request arguments, tool results or
remote exception bodies are logged. Audit events contain only client name, tool
name and outcome; denied calls are rejected before reaching the upstream.

The proxy relays tool results to authorized clients. Treat those results as
untrusted content. A tool allowlist is not a guarantee that a third-party server
implements its tools honestly. Use narrowly scoped upstream credentials.

## Lifecycle

The consumer supplies mapped identity plan/apply/verify and the existing mapped
application lifecycle. Identity verification is required before deployment;
it checks current contract convergence and exact secret permissions. Only the
selected service account reaches each container. No admin or provisioning token
is delivered to a workload.

Create a new Bao KV version to change configuration or rotate either token.
Update `config_ref.version` in YAML, review the plan and reapply. The public
Compose version marker forces recreation, and startup reads that pinned version.
Changes to the machine password use `identity.credential_revision` and the
reviewed identity lifecycle. Bao policies authorize paths, not fields or KV
versions. Someone who controls the workload identity can read other versions of
its own path; delete/revoke old credentials according to your retention policy.

Acceptance checks authenticated upstream tool discovery and denied tool/client
access without invoking an allowed business tool. The client hook verifies the
tailnet TLS certificate and unauthenticated HTTP 401 through the actual endpoint.
A health endpoint alone does
not prove upstream availability. Tests use synthetic credentials and in-memory
MCP servers, plus real HTTP authentication through ASGI. Live authorization,
TLS, tailnet grants, image build and upstream behavior require deployment checks.

Remote HTTP MCPs reuse this template with different bundles. OAuth-only endpoints
and locally launched `stdio` packages are not supported by this template. Local
packages need a separate pinned image/recipe and an explicit review of its code.

References: [FastMCP proxy](https://gofastmcp.com/servers/providers/proxy),
[Atlassian API-token authentication](https://developer.atlassian.com/cloud/rovo-mcp/guides/configuring-authentication-via-api-token/),
[Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve).

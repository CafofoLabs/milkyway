variable "oidc" {
  description = <<-EOT
    How this vault authenticates humans against the identity provider.

    `client_id` and `client_secret` come from the authentik module's outputs in
    the root module, so no credential is ever copied by hand.

    `allowed_redirect_uris` must list every address the browser can be sent
    back to: the UI callback, and the loopback address the CLI listens on
    during `bao login -method=oidc`. The provider rejects a callback that is
    not on this list, which is what stops an attacker redirecting a valid
    authorization code to themselves.
  EOT
  type = object({
    # The issuer, NOT the discovery document's URL. OpenBao appends
    # "/.well-known/openid-configuration" itself and rejects a value that
    # already contains it, then checks that the `issuer` field in the document
    # it fetches matches this string exactly — so it must be byte-identical to
    # what the provider publishes, trailing slash included.
    issuer_url = string

    client_id             = string
    client_secret         = string
    allowed_redirect_uris = list(string)

    # Where the auth method is mounted. Part of the UI callback URL, so
    # changing it means changing the redirect URIs registered with authentik.
    path = optional(string, "oidc")

    # `profile` is what carries group membership in authentik's default scope
    # mappings — without it `groups_claim` below has nothing to read.
    scopes = optional(list(string), ["openid", "email", "profile"])

    user_claim   = optional(string, "sub")
    groups_claim = optional(string, "groups")

    # Applied to every successful login, before group membership is
    # considered. Deliberately minimal: authorisation comes from the group
    # mapping, so a user in no mapped group should be able to do nothing.
    token_policies = optional(list(string), ["default"])
    token_ttl      = optional(number, 3600)
    token_max_ttl  = optional(number, 28800)
  })
}

variable "kv_mounts" {
  description = <<-EOT
    KV version 2 secret engines to create, keyed by a stable local name.

    v2 rather than v1 because it versions writes and supports soft deletes —
    an accidental overwrite is recoverable. Note that its API paths carry an
    extra segment (`<mount>/data/<secret>`), which policies must account for.
  EOT
  type = map(object({
    path        = string
    description = optional(string, "")
  }))
  default = {}
}

variable "policies" {
  description = <<-EOT
    Policies to create, keyed by a stable local name. Referenced by name from
    `group_roles` below.

    Remember that KV v2 splits its API paths: reading a secret is
    `<mount>/data/<path>`, listing it is `<mount>/metadata/<path>`, and
    permanently destroying versions is `<mount>/destroy/<path>`. A policy that
    only grants `<mount>/*` will surprise you.
  EOT
  type = map(object({
    name = string
    rules = list(object({
      path         = string
      capabilities = list(string)
      description  = optional(string, "")
    }))
  }))
  default = {}
}

variable "approles" {
  description = <<-EOT
    Machine identities, keyed by a stable local name. Empty by default, and an
    empty map creates no auth method at all.

    Read approle.tf before adding one. An AppRole is the only durable credential
    this module issues — everything else expires on its own — so the rule is
    that its policies reach as little as possible, and never the SSH signing
    path, which would make it an unattended shell on every host.

    `secret_id_ttl` of 0 means the credential never expires. That is the useful
    default for a control node that has to work unattended, and it is why
    `token_ttl` is short: the durable half only mints tokens, and the tokens are
    what a process actually holds.
  EOT
  type = map(object({
    name = string

    # By name, as declared in `policies` above. Where all the bounding happens.
    token_policies = list(string)

    token_ttl     = optional(number, 3600)
    token_max_ttl = optional(number, 28800)
    secret_id_ttl = optional(number, 0)
  }))
  default = {}

  validation {
    condition     = alltrue([for r in var.approles : length(r.token_policies) > 0])
    error_message = "Each AppRole must name at least one policy, or logging in with it grants nothing and says so nowhere."
  }
}

variable "ssh_ca" {
  description = <<-EOT
    The SSH certificate authority, or null to not have one.

    Hosts trust the CA's public key and accept any certificate it signed, so
    nothing has to be installed per person. Who may ask for a signature is
    decided by policy — see `policies` — which means it is decided by authentik
    group membership, like everything else.

    A role bounds what a signature may contain: which principals, for how long,
    and with which extensions. Splitting roles is how you differentiate access:
    one role per class of host, each allowing different principals, with the
    policy for each granted to a different group.

    `key_type` is the CA key's algorithm. ed25519 rather than RSA because the
    signature algorithm then needs no negotiation — RSA CAs additionally need
    `algorithm_signer` set, and getting it wrong produces certificates modern
    sshd silently refuses.
  EOT

  type = object({
    path     = optional(string, "ssh-client-signer")
    key_type = optional(string, "ed25519")

    roles = map(object({
      name = string

      # Principals. sshd accepts a certificate only if the account being logged
      # into is among them, so these are Unix usernames on the target hosts.
      allowed_users = list(string)
      default_user  = string

      # How long a certificate lives. This is the revocation mechanism, not a
      # convenience setting: there is no way to withdraw one early.
      #
      # In seconds, and a number rather than a duration string, because the API
      # answers in seconds. `"1h"` applies correctly and then reads back as
      # `"3600"`, which every subsequent plan proposes changing back — a diff
      # that never converges and quietly costs `tofu plan` its meaning as an
      # answer to "is anything outstanding?".
      ttl     = optional(number, 3600)
      max_ttl = optional(number, 28800)

      # `permit-pty` alone means an interactive shell and nothing else — no
      # port, agent or X11 forwarding.
      extensions = optional(list(string), ["permit-pty"])
    }))
  })

  default = null

  validation {
    condition = alltrue([
      for role in(var.ssh_ca == null ? {} : var.ssh_ca.roles) :
      contains(role.allowed_users, role.default_user)
    ])
    error_message = "Each SSH role's default_user must also appear in its allowed_users, or a request that names no principal is rejected."
  }
}

variable "group_roles" {
  description = <<-EOT
    Maps a group in the identity provider to policies in this vault.

    `external_group` is matched against the names in the token's groups claim,
    so it must be the group's name in authentik exactly. Membership is then
    managed entirely in authentik: adding someone to `platform-admins` there
    grants them these policies here on their next login, with no change to this
    repository.
  EOT
  type = map(object({
    external_group = string
    policies       = list(string)
  }))
  default = {}
}

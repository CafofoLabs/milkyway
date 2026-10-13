variable "instance_url" {
  description = <<-EOT
    Public base URL of the authentik instance, without a trailing slash. Used to
    build the OIDC endpoint URLs handed to downstream services.
  EOT
  type        = string

  validation {
    condition     = !endswith(var.instance_url, "/")
    error_message = "instance_url must not end with a trailing slash."
  }
}

variable "groups" {
  description = <<-EOT
    Groups to manage, keyed by a stable local name. Use these to gate access to
    applications rather than assigning users to applications directly.
  EOT
  type = map(object({
    name         = string
    is_superuser = optional(bool, false)
    attributes   = optional(map(any), {})

    # Numeric user PKs to place in this group. Day-to-day membership belongs in
    # authentik (or an LDAP/OIDC source), not here — this is for seeding the
    # first administrator so the instance is usable right after `tofu apply`.
    users = optional(list(number))

    # Group UUIDs to nest this group under. Not keys of this map: a resource
    # cannot reference its own for_each instances.
    parents = optional(list(string))
  }))
  default = {}
}

variable "oauth2_applications" {
  description = <<-EOT
    OIDC/OAuth2 applications. Use this for services that speak OpenID Connect
    natively (Grafana, Proxmox, Nextcloud, Argo CD, ...).

    `access_groups` restricts who can see and launch the application; leaving it
    empty means every authenticated user has access.
  EOT
  type = map(object({
    name                    = string
    slug                    = string
    description             = optional(string, "")
    launch_url              = optional(string)
    icon_url                = optional(string)
    group                   = optional(string, "")
    open_in_new_tab         = optional(bool, false)
    show_in_library         = optional(bool, true)
    publisher               = optional(string, "")
    policy_engine_mode      = optional(string, "any")
    backchannel_providers   = optional(list(number), [])
    provider_name           = optional(string)
    authorization_flow_slug = optional(string)
    invalidation_flow_slug  = optional(string)
    signing_key_name        = optional(string)

    redirect_uris = list(object({
      matching_mode = optional(string, "strict") # "strict" or "regex"
      url           = string
      # "authorization" for the login callback, "logout" for post-logout
      # redirects. The API always returns this key, so it must be set or every
      # plan shows drift.
      redirect_uri_type = optional(string, "authorization")
    }))

    client_type = optional(string, "confidential") # or "public" for SPAs/native
    sub_mode    = optional(string, "hashed_user_id")

    # Which OAuth2 flows the provider will honour. This MUST be set: authentik
    # defaults it to an empty list, and a provider with no grant types rejects
    # every authorization request with "invalid_request / The request is
    # otherwise malformed" — an error that says nothing about the cause and
    # only appears at the moment a human first tries to log in.
    #
    # The default here is the least-privilege pair for a confidential web
    # application. Add "client_credentials" for machine-to-machine access, or
    # the device-code grant for CLIs on machines with no browser. Do not add
    # "implicit" or "password"; both are discouraged by OAuth 2.1.
    grant_types = optional(list(string), ["authorization_code", "refresh_token"])

    access_groups = optional(list(string), [])

    access_token_validity  = optional(string, "hours=1")
    refresh_token_validity = optional(string, "days=30")
  }))
  default = {}
}

variable "proxy_applications" {
  description = <<-EOT
    Applications placed behind authentik's proxy outpost. Use this for services
    with no native SSO support — the outpost authenticates the request before it
    ever reaches the backend.

    mode:
      forward_single - one subdomain, proxy calls /outpost.goauthentik.io/auth/*
      forward_domain - one outpost serving a whole domain
      proxy          - authentik terminates and forwards to `internal_host`
  EOT
  type = map(object({
    name          = string
    slug          = string
    description   = optional(string, "")
    external_host = string
    internal_host = optional(string)
    mode          = optional(string, "forward_single")
    group         = optional(string, "")
    icon_url      = optional(string)

    # Paths that bypass authentication entirely (health checks, webhooks).
    skip_path_regex = optional(string)

    # Send the authenticated user as an HTTP Basic header to the backend.
    basic_auth_enabled   = optional(bool, false)
    basic_auth_user_attr = optional(string)
    basic_auth_pass_attr = optional(string)

    access_groups = optional(list(string), [])
  }))
  default = {}
}

variable "attach_proxy_to_embedded_outpost" {
  description = <<-EOT
    Attach every proxy provider to authentik's built-in embedded outpost. Turn
    this off when you run standalone outposts on the hosts being protected.
  EOT
  type        = bool
  default     = true
}

variable "embedded_outpost_name" {
  description = "Name of the embedded outpost to attach proxy providers to."
  type        = string
  default     = "authentik Embedded Outpost"
}

variable "brand" {
  description = <<-EOT
    Branding for the default domain. Set to null to leave the shipped brand
    untouched.
  EOT
  type = object({
    domain = string
    title  = string
    # Default to the assets authentik ships. Leaving these unset would clear
    # them on every apply, so the config has to state them explicitly.
    logo       = optional(string, "/static/dist/assets/icons/icon_left_brand.svg")
    favicon    = optional(string, "/static/dist/assets/icons/icon.png")
    is_default = optional(bool, true)
  })
  default = null
}

variable "system_settings" {
  description = "Instance-wide settings. Set to null to leave defaults alone."
  type = object({
    avatars                      = optional(string, "initials")
    default_token_duration       = optional(string, "days=30")
    default_token_length         = optional(number, 60)
    event_retention              = optional(string, "days=90")
    default_user_change_email    = optional(bool, false)
    default_user_change_name     = optional(bool, true)
    default_user_change_username = optional(bool, false)
    impersonation                = optional(bool, true)
  })
  default = null
}

# --- Flow slugs -------------------------------------------------------------
# authentik ships these flows out of the box. They are variables so a future
# environment can swap in custom flows (for example one enforcing MFA) without
# touching the module.

variable "signing_key_name" {
  description = <<-EOT
    Certificate keypair used to sign ID tokens. authentik generates this one on
    first boot; point it elsewhere to use a certificate you manage.

    It must exist — a provider with no signing key emits HS256 tokens, which
    OpenBao and most other relying parties refuse.
  EOT
  type        = string
  default     = "authentik Self-signed Certificate"
}

# --- Flow slugs -------------------------------------------------------------

variable "authorization_flow_slug" {
  description = "Flow used to authorize access to a provider."
  type        = string
  default     = "default-provider-authorization-implicit-consent"
}

variable "invalidation_flow_slug" {
  description = "Flow used when a provider session is invalidated (logout)."
  type        = string
  default     = "default-provider-invalidation-flow"
}

variable "authentication_flow_slug" {
  description = "Flow used to authenticate a user."
  type        = string
  default     = "default-authentication-flow"
}

output "groups" {
  description = "Managed groups, keyed by local name."
  value = {
    for k, g in authentik_group.this : k => {
      id   = g.id
      name = g.name
    }
  }
}

output "oauth2_endpoints" {
  description = <<-EOT
    The endpoint URLs of each OIDC application, and nothing else.

    Separate from `oauth2_applications` because that map contains client
    secrets and is therefore sensitive — and in OpenTofu, sensitivity is
    contagious: anything derived from a sensitive value becomes sensitive too,
    even a plain URL. Consuming a discovery URL from there would silently taint
    every downstream output that mentions it.

    Deriving these from the slug rather than reading them back off the provider
    is safe: it is authentik's endpoint layout, and the module already relies on
    it in `oauth2_applications`.
  EOT
  value = {
    for k, app in var.oauth2_applications : k => {
      name              = app.name
      slug              = app.slug
      issuer            = "${var.instance_url}/application/o/${app.slug}/"
      discovery_url     = "${var.instance_url}/application/o/${app.slug}/.well-known/openid-configuration"
      authorization_url = "${var.instance_url}/application/o/authorize/"
      token_url         = "${var.instance_url}/application/o/token/"
      userinfo_url      = "${var.instance_url}/application/o/userinfo/"
      jwks_url          = "${var.instance_url}/application/o/${app.slug}/jwks/"
      logout_url        = "${var.instance_url}/application/o/${app.slug}/end-session/"
    }
  }
}

output "oauth2_applications" {
  description = <<-EOT
    Everything a downstream service needs to complete its OIDC setup, including
    the client secret. Sensitive as a whole — read it with:
      tofu output -json oauth2_applications
    For the endpoints alone, use `oauth2_endpoints`, which is not sensitive.
  EOT
  sensitive   = true
  value = {
    for k, app in var.oauth2_applications : k => {
      name          = app.name
      slug          = app.slug
      client_id     = authentik_provider_oauth2.this[k].client_id
      client_secret = authentik_provider_oauth2.this[k].client_secret

      # Standard authentik endpoint layout, derived from the application slug.
      issuer            = "${var.instance_url}/application/o/${app.slug}/"
      discovery_url     = "${var.instance_url}/application/o/${app.slug}/.well-known/openid-configuration"
      authorization_url = "${var.instance_url}/application/o/authorize/"
      token_url         = "${var.instance_url}/application/o/token/"
      userinfo_url      = "${var.instance_url}/application/o/userinfo/"
      jwks_url          = "${var.instance_url}/application/o/${app.slug}/jwks/"
      logout_url        = "${var.instance_url}/application/o/${app.slug}/end-session/"
    }
  }
}

output "proxy_applications" {
  description = <<-EOT
    Proxy-protected applications and where the reverse proxy must send its auth
    subrequest.

    In forward_single mode the outpost answers on the application's own host; in
    forward_domain a single outpost answers on the authentik host for the whole
    domain. Append your proxy's flavour to `auth_endpoint_base` — `/nginx`,
    `/traefik` or `/caddy`.
  EOT
  value = {
    for k, app in var.proxy_applications : k => {
      name          = app.name
      slug          = app.slug
      external_host = app.external_host
      mode          = app.mode

      auth_endpoint_base = format(
        "%s/outpost.goauthentik.io/auth",
        app.mode == "forward_domain" ? var.instance_url : trimsuffix(app.external_host, "/")
      )

      # Redirect target for a 401 from the auth subrequest.
      sign_in_url = format(
        "%s/outpost.goauthentik.io/start",
        app.mode == "forward_domain" ? var.instance_url : trimsuffix(app.external_host, "/")
      )
    }
  }
}

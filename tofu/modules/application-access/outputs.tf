output "oidc_endpoints" {
  description = "Public OIDC metadata for this application; clients use discovery and validate the issuer."
  value = {
    issuer            = "${var.identity_url}/application/o/${var.slug}/"
    discovery_url     = "${var.identity_url}/application/o/${var.slug}/.well-known/openid-configuration"
    authorization_url = "${var.identity_url}/application/o/authorize/"
    token_url         = "${var.identity_url}/application/o/token/"
    userinfo_url      = "${var.identity_url}/application/o/userinfo/"
    jwks_url          = "${var.identity_url}/application/o/${var.slug}/jwks/"
    logout_url        = "${var.identity_url}/application/o/${var.slug}/end-session/"
  }
}

output "oidc_client" {
  description = "Server-side OIDC credential; deliver only to the application's deployment secret store."
  sensitive   = true
  value = {
    client_id     = authentik_provider_oauth2.this.client_id
    client_secret = authentik_provider_oauth2.this.client_secret
  }
}

output "approle_credentials" {
  description = "Own-prefix-only machine identity; never share with another application or browser."
  sensitive   = true
  value = {
    backend   = "approle"
    role_id   = vault_approle_auth_backend_role.this.role_id
    secret_id = vault_approle_auth_backend_role_secret_id.this.secret_id
  }
}

output "secret_prefix" {
  description = "This application's fixed KV v2 prefix; excludes other applications and platform paths."
  value       = local.secret_prefix
}

output "secret_policy" {
  description = "Non-secret policy text for contract review and isolation verification."
  value       = local.secret_policy
}

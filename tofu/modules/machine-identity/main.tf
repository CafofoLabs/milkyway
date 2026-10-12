terraform {
  required_version = ">= 1.10.0"
  required_providers {
    authentik = { source = "goauthentik/authentik", version = "~> 2026.5.0" }
    vault     = { source = "hashicorp/vault", version = "~> 5.10" }
  }
}
variable "settings" {
  description = "Trusted deployment catalog. This module owns only its dedicated M2M provider and JWT mount."
  type = object({
    deployment         = string, identity_url = string, vault_url = string,
    slug               = string, auth_mount = string, signing_key = string,
    authorization_flow = string, invalidation_flow = string,
    jwt_ttl            = number, token_ttl = number, token_max_ttl = number
  })
  validation {
    condition = alltrue([
      can(regex("^[a-z][a-z0-9-]{0,47}$", var.settings.deployment)),
      can(regex("^[a-z][a-z0-9-]{0,47}$", var.settings.slug)),
      can(regex("^[a-z][a-z0-9-]{0,47}$", var.settings.auth_mount)),
      !contains(["oidc", "approle", "token"], var.settings.auth_mount),
      var.settings.jwt_ttl >= 60, var.settings.jwt_ttl <= 3600,
      var.settings.token_ttl >= 60, var.settings.token_max_ttl >= var.settings.token_ttl,
      var.settings.token_max_ttl <= 3600
    ])
    error_message = "Use a dedicated JWT mount, safe deployment names and token lifetimes between one minute and one hour."
  }
}
data "authentik_flow" "authorization" { slug = var.settings.authorization_flow }
data "authentik_flow" "invalidation" { slug = var.settings.invalidation_flow }
data "authentik_certificate_key_pair" "signing" { name = var.settings.signing_key }
resource "authentik_property_mapping_provider_scope" "machine" {
  name       = "MilkyWay ${var.settings.deployment} machine identity"
  scope_name = "milkyway-service"
  expression = <<-PY
    return {
      "service_account_id": str(request.user.pk),
      "application": request.user.attributes.get("milkyway_application", ""),
      "environment": request.user.attributes.get("milkyway_environment", ""),
    }
  PY
}
resource "authentik_provider_oauth2" "machine" {
  name                  = "MilkyWay ${var.settings.deployment} services"
  client_id             = var.settings.slug
  client_type           = "confidential"
  issuer_mode           = "per_provider"
  sub_mode              = "user_id"
  grant_types           = ["client_credentials"]
  authorization_flow    = data.authentik_flow.authorization.id
  invalidation_flow     = data.authentik_flow.invalidation.id
  signing_key           = data.authentik_certificate_key_pair.signing.id
  property_mappings     = [authentik_property_mapping_provider_scope.machine.id]
  access_token_validity = "seconds=${var.settings.jwt_ttl}"
  allowed_redirect_uris = []
}
resource "authentik_application" "machine" {
  name               = "MilkyWay ${var.settings.deployment} services"
  slug               = var.settings.slug
  protocol_provider  = authentik_provider_oauth2.machine.id
  policy_engine_mode = "all"
}
resource "authentik_policy_expression" "machine" {
  name       = "MilkyWay ${var.settings.deployment} service accounts only"
  expression = "return request.user.type == 'service_account' and request.user.path.startswith('service-accounts/${var.settings.deployment}/')"
}
resource "authentik_policy_binding" "machine" {
  target         = authentik_application.machine.uuid
  policy         = authentik_policy_expression.machine.id
  order          = 0
  enabled        = true
  failure_result = false
}
resource "vault_jwt_auth_backend" "machine" {
  depends_on         = [authentik_application.machine, authentik_policy_binding.machine]
  path               = var.settings.auth_mount
  type               = "jwt"
  jwks_url           = "${var.settings.identity_url}/application/o/${var.settings.slug}/jwks/"
  bound_issuer       = "${var.settings.identity_url}/application/o/${var.settings.slug}/"
  jwt_supported_algs = ["RS256"]
  tune {
    default_lease_ttl = "${var.settings.token_ttl}s"
    max_lease_ttl     = "${var.settings.token_max_ttl}s"
  }
}
output "connection" {
  value = {
    client_id      = var.settings.slug
    issuer         = "${var.settings.identity_url}/application/o/${var.settings.slug}/"
    token_url      = "${var.settings.identity_url}/application/o/token/"
    vault_url      = var.settings.vault_url
    auth_mount     = vault_jwt_auth_backend.machine.path
    mount_accessor = vault_jwt_auth_backend.machine.accessor
    scope          = "milkyway-service"
  }
}

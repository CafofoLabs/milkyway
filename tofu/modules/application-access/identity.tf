# Reuse the platform's existing flows, scopes and signing key; never own them here.
data "authentik_flow" "authorization" {
  slug = var.authorization_flow_slug
}

data "authentik_flow" "invalidation" {
  slug = var.invalidation_flow_slug
}

data "authentik_certificate_key_pair" "signing" {
  name = var.signing_key_name
}

data "authentik_property_mapping_provider_scope" "oidc" {
  managed_list = [
    "goauthentik.io/providers/oauth2/scope-openid",
    "goauthentik.io/providers/oauth2/scope-email",
    "goauthentik.io/providers/oauth2/scope-profile",
  ]
}

resource "random_id" "client" {
  byte_length = 16
}

resource "authentik_provider_oauth2" "this" {
  name                   = "Application: ${var.slug}"
  client_id              = random_id.client.hex
  client_type            = "confidential"
  issuer_mode            = "per_provider"
  sub_mode               = "hashed_user_id"
  grant_types            = ["authorization_code", "refresh_token"]
  signing_key            = data.authentik_certificate_key_pair.signing.id
  authorization_flow     = data.authentik_flow.authorization.id
  invalidation_flow      = data.authentik_flow.invalidation.id
  property_mappings      = data.authentik_property_mapping_provider_scope.oidc.ids
  access_token_validity  = "hours=1"
  refresh_token_validity = "days=30"

  allowed_redirect_uris = [for uri in var.redirect_uris : {
    matching_mode     = "strict"
    url               = uri
    redirect_uri_type = "authorization"
  }]
}

resource "authentik_application" "this" {
  name               = var.name
  slug               = var.slug
  protocol_provider  = authentik_provider_oauth2.this.id
  meta_launch_url    = var.launch_url
  policy_engine_mode = "any"
}

resource "authentik_policy_binding" "access" {
  for_each = toset(var.access_group_ids)

  target         = authentik_application.this.uuid
  group          = each.value
  order          = index(sort(var.access_group_ids), each.value)
  enabled        = true
  failure_result = false
}

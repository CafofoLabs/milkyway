# Baseline authentik configuration: the objects that every environment needs
# before any application can be onboarded.

# --- Flows ------------------------------------------------------------------
# Looked up rather than created, so the module composes with authentik's
# shipped defaults instead of fighting them.

data "authentik_flow" "authorization" {
  slug = var.authorization_flow_slug
}

data "authentik_flow" "invalidation" {
  slug = var.invalidation_flow_slug
}

data "authentik_flow" "authentication" {
  slug = var.authentication_flow_slug
}

# --- Scope mappings ---------------------------------------------------------
# The managed scopes authentik ships. Every OIDC provider gets these so that
# downstream services can read the user's identity and group membership.

data "authentik_property_mapping_provider_scope" "application" {
  for_each = var.oauth2_applications

  managed_list = concat([
    "goauthentik.io/providers/oauth2/scope-openid",
    "goauthentik.io/providers/oauth2/scope-email",
    "goauthentik.io/providers/oauth2/scope-profile",
  ], each.value.scope_mappings)
}

# --- Groups -----------------------------------------------------------------

resource "authentik_group" "this" {
  for_each = var.groups

  name         = each.value.name
  is_superuser = each.value.is_superuser
  parents      = each.value.parents
  users        = each.value.users
  attributes   = length(each.value.attributes) > 0 ? jsonencode(each.value.attributes) : null
}

# --- Instance settings ------------------------------------------------------

resource "authentik_system_settings" "this" {
  count = var.system_settings == null ? 0 : 1

  avatars                      = var.system_settings.avatars
  default_token_duration       = var.system_settings.default_token_duration
  default_token_length         = var.system_settings.default_token_length
  event_retention              = var.system_settings.event_retention
  default_user_change_email    = var.system_settings.default_user_change_email
  default_user_change_name     = var.system_settings.default_user_change_name
  default_user_change_username = var.system_settings.default_user_change_username
  impersonation                = var.system_settings.impersonation
}

resource "authentik_brand" "this" {
  count = var.brand == null ? 0 : 1

  domain           = var.brand.domain
  branding_title   = var.brand.title
  branding_logo    = var.brand.logo
  branding_favicon = var.brand.favicon
  default          = var.brand.is_default

  flow_authentication = data.authentik_flow.authentication.id
}

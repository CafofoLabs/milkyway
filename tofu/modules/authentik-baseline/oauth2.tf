# OIDC/OAuth2 applications — for services that speak OpenID Connect natively.

# The keypair that signs ID tokens.
#
# Without one, authentik falls back to HS256 — a symmetric signature derived
# from the client secret. That is legal OIDC and it is also useless to most
# relying parties: OpenBao, and every library built on go-oidc, accept only
# asymmetric algorithms and reject the token with
# "unexpected signature algorithm HS256; expected [RS256]".
#
# Looked up rather than created, so the module composes with the keypair
# authentik generates on first boot instead of managing certificate lifetime.
data "authentik_certificate_key_pair" "signing" {
  name = var.signing_key_name
}

# Client IDs are generated rather than hand-written so they are unique and
# non-guessable, but stay stable across applies because they live in state.
resource "random_id" "oauth2_client_id" {
  for_each    = var.oauth2_applications
  byte_length = 16
}

resource "authentik_provider_oauth2" "this" {
  for_each = var.oauth2_applications

  name      = each.value.name
  client_id = random_id.oauth2_client_id[each.key].hex

  client_type = each.value.client_type
  sub_mode    = each.value.sub_mode
  grant_types = each.value.grant_types
  signing_key = data.authentik_certificate_key_pair.signing.id

  authorization_flow = data.authentik_flow.authorization.id
  invalidation_flow  = data.authentik_flow.invalidation.id

  property_mappings = data.authentik_property_mapping_provider_scope.oidc.ids

  access_token_validity  = each.value.access_token_validity
  refresh_token_validity = each.value.refresh_token_validity

  allowed_redirect_uris = [
    for uri in each.value.redirect_uris : {
      matching_mode     = uri.matching_mode
      url               = uri.url
      redirect_uri_type = uri.redirect_uri_type
    }
  ]
}

resource "authentik_application" "oauth2" {
  for_each = var.oauth2_applications

  name              = each.value.name
  slug              = each.value.slug
  protocol_provider = authentik_provider_oauth2.this[each.key].id

  meta_description = each.value.description
  meta_launch_url  = each.value.launch_url
  meta_icon        = each.value.icon_url
  group            = each.value.group
  open_in_new_tab  = each.value.open_in_new_tab
}

# Access control. Without a binding an application is visible to every
# authenticated user, so each entry in `access_groups` adds an allow rule.
resource "authentik_policy_binding" "oauth2_access" {
  for_each = {
    for pair in flatten([
      for app_key, app in var.oauth2_applications : [
        for group_key in app.access_groups : {
          key       = "${app_key}:${group_key}"
          app_key   = app_key
          group_key = group_key
        }
      ]
    ]) : pair.key => pair
  }

  target = authentik_application.oauth2[each.value.app_key].uuid
  group  = authentik_group.this[each.value.group_key].id
  order  = index(var.oauth2_applications[each.value.app_key].access_groups, each.value.group_key)
}

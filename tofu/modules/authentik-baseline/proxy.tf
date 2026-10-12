# Proxy applications — forward-auth for services with no native SSO support.

resource "authentik_provider_proxy" "this" {
  for_each = var.proxy_applications

  name          = each.value.name
  mode          = each.value.mode
  external_host = each.value.external_host

  # Only meaningful in "proxy" mode, where authentik forwards the request
  # itself. Forward-auth modes leave routing to the reverse proxy.
  internal_host = each.value.mode == "proxy" ? each.value.internal_host : null

  authorization_flow = data.authentik_flow.authorization.id
  invalidation_flow  = data.authentik_flow.invalidation.id

  skip_path_regex = each.value.skip_path_regex

  basic_auth_enabled            = each.value.basic_auth_enabled
  basic_auth_username_attribute = each.value.basic_auth_user_attr
  basic_auth_password_attribute = each.value.basic_auth_pass_attr
}

resource "authentik_application" "proxy" {
  for_each = var.proxy_applications

  name              = each.value.name
  slug              = each.value.slug
  protocol_provider = authentik_provider_proxy.this[each.key].id

  meta_description = each.value.description
  meta_launch_url  = each.value.external_host
  meta_icon        = each.value.icon_url
  group            = each.value.group
}

resource "authentik_policy_binding" "proxy_access" {
  for_each = {
    for pair in flatten([
      for app_key, app in var.proxy_applications : [
        for group_key in app.access_groups : {
          key       = "${app_key}:${group_key}"
          app_key   = app_key
          group_key = group_key
        }
      ]
    ]) : pair.key => pair
  }

  target = authentik_application.proxy[each.value.app_key].uuid
  group  = authentik_group.this[each.value.group_key].id
  order  = index(var.proxy_applications[each.value.app_key].access_groups, each.value.group_key)
}

# A proxy provider does nothing until an outpost serves it. Attaching to the
# embedded outpost is the zero-infrastructure option and is enough until you
# need an outpost running next to the protected service.
data "authentik_outpost" "embedded" {
  count = var.attach_proxy_to_embedded_outpost && length(var.proxy_applications) > 0 ? 1 : 0
  name  = var.embedded_outpost_name
}

resource "authentik_outpost_provider_attachment" "embedded" {
  for_each = var.attach_proxy_to_embedded_outpost ? var.proxy_applications : {}

  outpost           = data.authentik_outpost.embedded[0].id
  protocol_provider = authentik_provider_proxy.this[each.key].id
}

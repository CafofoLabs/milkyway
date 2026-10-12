terraform {
  required_version = ">= 1.10.0"
  required_providers {
    authentik = { source = "goauthentik/authentik", version = "~> 2026.5.0" }
    vault     = { source = "hashicorp/vault", version = "~> 5.10" }
  }
}
variable "contract" {
  description = "Validated and authorized contract compiled by scripts/service_identity.py."
  type = object({
    application = string, environment = string, deployment = string,
    profiles    = map(object({ policies = list(string) })),
    accounts = map(object({
      enabled = bool, roles = list(string), credential_revision = number,
      reads   = list(object({ mount = string, path = string, recursive = bool }))
    }))
  })
  validation {
    condition = alltrue([
      can(regex("^[a-z][a-z0-9-]{0,47}$", var.contract.application)),
      can(regex("^[a-z][a-z0-9-]{0,47}$", var.contract.environment)),
      can(regex("^[a-z][a-z0-9-]{0,47}$", var.contract.deployment)),
      alltrue([for name, account in var.contract.accounts :
        startswith(name, "svc-${var.contract.application}-${var.contract.environment}-") || name == "svc-${var.contract.application}-${var.contract.environment}"
      ]),
      alltrue(flatten([for a in var.contract.accounts : [for r in a.reads :
        can(regex("^[a-z][a-z0-9-]*$", r.mount)) &&
        can(regex("^[a-zA-Z0-9_-]+(/[a-zA-Z0-9_-]+)*$", r.path))
      ]]))
    ])
    error_message = "Names and secret paths must be scoped and contain no wildcards or traversal."
  }
}
variable "settings" {
  type = object({ auth_mount = string, token_ttl = number, token_max_ttl = number, slug = string })
}
data "vault_auth_backend" "machine" { path = var.settings.auth_mount }
locals {
  prefix = "mw-${var.contract.deployment}-${substr(sha256("${var.contract.application}/${var.contract.environment}"), 0, 16)}"
  active = { for name, a in var.contract.accounts : name => a if a.enabled }
}
resource "authentik_user" "service" {
  for_each  = var.contract.accounts
  username  = each.key
  name      = each.key
  type      = "service_account"
  is_active = each.value.enabled
  path      = "service-accounts/${var.contract.deployment}/${var.contract.application}/${var.contract.environment}"
  attributes = jsonencode({
    milkyway_application = var.contract.application,
    milkyway_environment = var.contract.environment
  })
}
# Only these scoped groups own their membership lists. Shared baseline groups
# and the computed authentik_user.groups field are never reconciled here.
resource "authentik_group" "profile" {
  for_each     = var.contract.profiles
  name         = "${local.prefix}-${each.key}"
  is_superuser = false
  users = [for name, a in var.contract.accounts : tonumber(authentik_user.service[name].id)
    if a.enabled && contains(a.roles, each.key)
  ]
}
resource "terraform_data" "credential_revision" {
  for_each = local.active
  input    = each.value.credential_revision
}
resource "authentik_token" "bootstrap" {
  for_each     = local.active
  identifier   = "mw-${sha256("${local.prefix}/${each.key}")}-r${each.value.credential_revision}"
  user         = tonumber(authentik_user.service[each.key].id)
  intent       = "app_password"
  expiring     = false
  retrieve_key = true
  description  = "Application bootstrap credential; rotate by increasing credentialRevision."
  lifecycle {
    replace_triggered_by = [terraform_data.credential_revision[each.key]]
  }
}
resource "vault_identity_entity" "service" {
  for_each = var.contract.accounts
  name     = "${local.prefix}-${each.key}"
  disabled = !each.value.enabled
  metadata = { application = var.contract.application, environment = var.contract.environment }
}
resource "vault_identity_entity_alias" "service" {
  for_each       = var.contract.accounts
  name           = authentik_user.service[each.key].id
  mount_accessor = data.vault_auth_backend.machine.accessor
  canonical_id   = vault_identity_entity.service[each.key].id
}
resource "vault_policy" "service" {
  for_each = var.contract.accounts
  name     = "${local.prefix}-${each.key}"
  policy = each.value.enabled ? join("\n", concat(
    flatten([for r in each.value.reads : [
      "path ${jsonencode("${r.mount}/data/${r.path}")} { capabilities = [\"read\"] }",
      r.recursive ? "path ${jsonencode("${r.mount}/data/${r.path}/*")} { capabilities = [\"read\"] }" : ""
    ]]),
    [
      "path \"auth/token/lookup-self\" { capabilities = [\"read\"] }",
      "path \"auth/token/renew-self\" { capabilities = [\"update\"] }",
      "path \"auth/token/revoke-self\" { capabilities = [\"update\"] }",
      "path \"sys/capabilities-self\" { capabilities = [\"update\"] }"
    ]
  )) : ""
}
resource "vault_jwt_auth_backend_role" "service" {
  for_each          = local.active
  backend           = var.settings.auth_mount
  role_name         = "${local.prefix}-${each.key}"
  role_type         = "jwt"
  user_claim        = "service_account_id"
  bound_audiences   = [var.settings.slug]
  bound_claims_type = "string"
  bound_claims = {
    service_account_id = authentik_user.service[each.key].id
    application        = var.contract.application
    environment        = var.contract.environment
  }
  token_policies = concat([vault_policy.service[each.key].name], distinct(flatten([
    for role in each.value.roles : var.contract.profiles[role].policies
  ])))
  token_no_default_policy = true
  token_type              = "service"
  token_ttl               = var.settings.token_ttl
  token_max_ttl           = var.settings.token_max_ttl
  token_explicit_max_ttl  = var.settings.token_max_ttl
  depends_on              = [vault_identity_entity_alias.service]
}
output "credentials" {
  sensitive = true
  value = { for name, a in local.active : name => {
    username = name
    password = authentik_token.bootstrap[name].key
    role     = vault_jwt_auth_backend_role.service[name].role_name
  } }
}
output "accounts" {
  value = { for name, a in var.contract.accounts : name => {
    enabled = a.enabled, principal = authentik_user.service[name].id,
    role    = a.enabled ? vault_jwt_auth_backend_role.service[name].role_name : null
  } }
}

terraform {
  required_providers {
    authentik = { source = "goauthentik/authentik", version = "~> 2026.5.0" }
    vault     = { source = "hashicorp/vault", version = "~> 5.10" }
  }
}
locals {
  apps = toset(["inventory", "billing"])
}
module "identity" {
  for_each = local.apps
  source   = "../../.."
  settings = { auth_mount = "service-jwt", slug = "services", token_ttl = 300, token_max_ttl = 900 }
  contract = {
    application = each.key, environment = "dev", deployment = "example",
    profiles    = { application-service = { policies = [] } },
    accounts = { "svc-${each.key}-dev" = {
      enabled = true, roles = ["application-service"], credential_revision = 1,
      reads   = [{ mount = "secret", path = "apps/${each.key}/dev", recursive = true }]
    } }
  }
}
output "accounts" { value = { for app, identity in module.identity : app => identity.accounts } }

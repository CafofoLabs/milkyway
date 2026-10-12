terraform {
  required_version = ">= 1.10.0, < 2.0.0"
  required_providers {
    authentik = { source = "goauthentik/authentik", version = "~> 2026.5.0" }
    vault     = { source = "hashicorp/vault", version = "~> 5.10" }
  }
  backend "local" {}
  encryption {
    key_provider "pbkdf2" "state" { passphrase = var.state_encryption_passphrase }
    method "aes_gcm" "state" { keys = key_provider.pbkdf2.state }
    state {
      method   = method.aes_gcm.state
      enforced = true
    }
    plan {
      method   = method.aes_gcm.state
      enforced = true
    }
  }
}
variable "state_encryption_passphrase" {
  type      = string
  sensitive = true
}
variable "authentik_api_token" {
  type      = string
  sensitive = true
}
variable "settings" {
  type = object({
    deployment         = string, identity_url = string, vault_url = string,
    slug               = string, auth_mount = string, signing_key = string,
    authorization_flow = string, invalidation_flow = string,
    jwt_ttl            = number, token_ttl = number, token_max_ttl = number
  })
}
provider "authentik" {
  url   = var.settings.identity_url
  token = var.authentik_api_token
}
provider "vault" {
  address          = var.settings.vault_url
  skip_child_token = true
}
module "identity" {
  source   = "MODULE_SOURCE"
  settings = var.settings
}
output "connection" { value = module.identity.connection }

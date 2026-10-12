terraform {
  required_version = ">= 1.10.0"
  required_providers {
    authentik = {
      source  = "goauthentik/authentik"
      version = "~> 2026.5.0"
    }
    vault = {
      source  = "hashicorp/vault"
      version = "~> 5.10"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  backend "local" {
    path = ".milkyway/state/application.tfstate"
  }

  encryption {
    key_provider "pbkdf2" "state" {
      passphrase = var.state_encryption_passphrase
    }
    method "aes_gcm" "state" {
      keys = key_provider.pbkdf2.state
    }
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

# Provisioning tokens come from TF_VAR_authentik_api_token and VAULT_TOKEN at runtime.
provider "authentik" {
  url   = var.identity_url
  token = var.authentik_api_token
}
provider "vault" {
  address          = var.vault_url
  skip_child_token = true
}

module "access" {
  source = "../../tofu/modules/application-access"

  slug             = var.slug
  name             = var.name
  identity_url     = var.identity_url
  launch_url       = var.launch_url
  redirect_uris    = var.redirect_uris
  access_group_ids = var.access_group_ids
}

output "connection" {
  description = "Non-secret application connection metadata."
  value = {
    oidc          = module.access.oidc_endpoints
    secret_prefix = module.access.secret_prefix
  }
}

output "deployment_credentials" {
  description = "Consume programmatically into the app's private deployment secret store; never print."
  sensitive   = true
  value = {
    oidc    = module.access.oidc_client
    openbao = module.access.approle_credentials
  }
}

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
}

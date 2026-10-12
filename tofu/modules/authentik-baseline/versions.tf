terraform {
  required_version = ">= 1.6.0"

  required_providers {
    authentik = {
      source = "goauthentik/authentik"
      # The provider is versioned in lockstep with the server. Keep this on the
      # same release line as AUTHENTIK_TAG in the compose stack.
      version = "~> 2026.5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

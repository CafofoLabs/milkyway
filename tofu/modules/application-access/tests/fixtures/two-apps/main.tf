terraform {
  required_providers {
    authentik = { source = "goauthentik/authentik" }
    vault     = { source = "hashicorp/vault" }
    random    = { source = "hashicorp/random" }
  }
}

module "alpha" {
  source           = "../../.."
  slug             = "alpha"
  name             = "Alpha"
  identity_url     = "https://idp.example.test"
  launch_url       = "https://alpha.example.test"
  redirect_uris    = ["https://alpha.example.test/callback"]
  access_group_ids = ["00000000-0000-0000-0000-000000000001"]
}

module "beta" {
  source           = "../../.."
  slug             = "beta"
  name             = "Beta"
  identity_url     = "https://idp.example.test"
  launch_url       = "https://beta.example.test"
  redirect_uris    = ["https://beta.example.test/callback"]
  access_group_ids = ["00000000-0000-0000-0000-000000000001"]
}

output "contracts" {
  value = {
    alpha = { prefix = module.alpha.secret_prefix, policy = module.alpha.secret_policy, issuer = module.alpha.oidc_endpoints.issuer }
    beta  = { prefix = module.beta.secret_prefix, policy = module.beta.secret_policy, issuer = module.beta.oidc_endpoints.issuer }
  }
}

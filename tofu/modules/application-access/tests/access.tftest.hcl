mock_provider "authentik" {
  mock_resource "authentik_provider_oauth2" {
    defaults = { id = "101" }
  }
}
mock_provider "vault" {}
mock_provider "random" {}

run "standard_contract" {
  command = plan
  variables {
    slug             = "example-app"
    name             = "Example App"
    identity_url     = "https://idp.example.test"
    launch_url       = "https://app.example.test"
    redirect_uris    = ["https://app.example.test/callback"]
    access_group_ids = ["00000000-0000-0000-0000-000000000001"]
  }
  assert {
    condition     = output.secret_prefix == "apps/example-app" && output.oidc_endpoints.issuer == "https://idp.example.test/application/o/example-app/"
    error_message = "The app's namespace and issuer must be derived from its stable slug."
  }
  assert {
    condition     = authentik_provider_oauth2.this.client_type == "confidential" && authentik_provider_oauth2.this.allowed_redirect_uris[0].matching_mode == "strict"
    error_message = "The default contract requires native confidential OIDC and an exact callback."
  }
  assert {
    condition     = vault_approle_auth_backend_role.this.token_no_default_policy && length(vault_approle_auth_backend_role.this.token_policies) == 1 && contains(vault_approle_auth_backend_role.this.token_policies, "app-example-app") && vault_approle_auth_backend_role.this.bind_secret_id
    error_message = "The machine identity must require its credential and receive only its app policy."
  }
  assert {
    condition     = !strcontains(output.secret_policy, "ssh") && !strcontains(output.secret_policy, "platform/") && !strcontains(output.secret_policy, "sys/") && !strcontains(output.secret_policy, "create") && !strcontains(output.secret_policy, "delete")
    error_message = "App credentials must not sign SSH, administer Bao, write secrets or reach platform paths."
  }
}

run "two_apps_are_isolated" {
  command = plan
  module {
    source = "./tests/fixtures/two-apps"
  }
  assert {
    condition     = output.contracts.alpha.prefix != output.contracts.beta.prefix && output.contracts.alpha.issuer != output.contracts.beta.issuer
    error_message = "Independent apps must not share namespaces or OIDC issuers."
  }
  assert {
    condition     = strcontains(output.contracts.alpha.policy, "secret/data/apps/alpha/*") && !strcontains(output.contracts.alpha.policy, "apps/beta") && strcontains(output.contracts.beta.policy, "secret/data/apps/beta/*") && !strcontains(output.contracts.beta.policy, "apps/alpha")
    error_message = "Each app policy must grant only its own exact prefix and descendants."
  }
}

run "reject_path_injection" {
  command = plan
  variables {
    slug             = "../platform"
    name             = "Invalid App"
    identity_url     = "https://idp.example.test"
    launch_url       = "https://app.example.test"
    redirect_uris    = ["https://app.example.test/callback"]
    access_group_ids = ["00000000-0000-0000-0000-000000000001"]
  }
  expect_failures = [var.slug]
}

run "reject_unrestricted_access" {
  command = plan
  variables {
    slug             = "example-app"
    name             = "Invalid App"
    identity_url     = "https://idp.example.test"
    launch_url       = "https://app.example.test"
    redirect_uris    = ["https://app.example.test/callback"]
    access_group_ids = []
  }
  expect_failures = [var.access_group_ids]
}

run "reject_wildcard_callback" {
  command = plan
  variables {
    slug             = "example-app"
    name             = "Invalid App"
    identity_url     = "https://idp.example.test"
    launch_url       = "https://app.example.test"
    redirect_uris    = ["https://app.example.test/*"]
    access_group_ids = ["00000000-0000-0000-0000-000000000001"]
  }
  expect_failures = [var.redirect_uris]
}

run "reject_mount_injection" {
  command = plan
  variables {
    slug             = "example-app"
    name             = "Invalid App"
    identity_url     = "https://idp.example.test"
    launch_url       = "https://app.example.test"
    redirect_uris    = ["https://app.example.test/callback"]
    access_group_ids = ["00000000-0000-0000-0000-000000000001"]
    vault_mount      = "secret/*"
  }
  expect_failures = [var.vault_mount]
}

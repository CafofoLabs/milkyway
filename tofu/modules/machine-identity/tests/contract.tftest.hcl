mock_provider "authentik" {
  mock_resource "authentik_provider_oauth2" { defaults = { id = "123" } }
}
mock_provider "vault" {}
variables {
  settings = {
    deployment         = "example", identity_url = "https://idp.example.test", vault_url = "https://bao.example.test",
    slug               = "example-services", auth_mount = "service-jwt", signing_key = "test-key",
    authorization_flow = "authorization", invalidation_flow = "invalidation",
    jwt_ttl            = 300, token_ttl = 300, token_max_ttl = 900
  }
}
run "machine_is_separate_from_humans" {
  command = plan
  assert {
    condition     = vault_jwt_auth_backend.machine.type == "jwt" && vault_jwt_auth_backend.machine.path == "service-jwt" && vault_jwt_auth_backend.machine.bound_issuer == "https://idp.example.test/application/o/example-services/"
    error_message = "The machine backend must use its dedicated mount and exact issuer."
  }
  assert {
    condition     = authentik_provider_oauth2.machine.grant_types == tolist(["client_credentials"]) && authentik_provider_oauth2.machine.signing_key != "" && length(authentik_provider_oauth2.machine.allowed_redirect_uris) == 0
    error_message = "Use only M2M grants and asymmetric signing without browser callbacks."
  }
  assert {
    condition     = strcontains(authentik_property_mapping_provider_scope.machine.expression, "str(request.user.pk)") && strcontains(authentik_policy_expression.machine.expression, "service_account")
    error_message = "Bind tokens to an immutable account identifier and reject human logins."
  }
}
run "human_mount_cannot_be_replaced" {
  command = plan
  variables {
    settings = {
      deployment         = "example", identity_url = "https://idp.example.test", vault_url = "https://bao.example.test",
      slug               = "example-services", auth_mount = "oidc", signing_key = "test-key",
      authorization_flow = "authorization", invalidation_flow = "invalidation",
      jwt_ttl            = 300, token_ttl = 300, token_max_ttl = 900
    }
  }
  expect_failures = [var.settings]
}

mock_provider "authentik" {
  mock_resource "authentik_provider_oauth2" {
    defaults = { id = "101" }
  }
}
mock_provider "random" {}

variables {
  instance_url = "https://identity.example.test"
  groups = {
    operators = { name = "platform-operators" }
  }
  oauth2_applications = {
    grafana = {
      name          = "Grafana"
      slug          = "grafana"
      redirect_uris = [{ url = "https://grafana.example.test/login/generic_oauth" }]
      access_groups = ["operators"]
    }
  }
}

run "oidc_group_contract" {
  command = plan
  assert {
    condition     = output.oauth2_endpoints.grafana.issuer == "https://identity.example.test/application/o/grafana/"
    error_message = "The issuer must stay tied to the stable service domain."
  }
  assert {
    condition     = length(authentik_policy_binding.oauth2_access) == 1
    error_message = "The application must bind access to the declared group."
  }
}

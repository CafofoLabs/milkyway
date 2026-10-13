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

run "application_metadata_and_native_oidc_contract" {
  command = plan
  variables {
    oauth2_applications = {
      hermes = {
        name                    = "Research dashboard"
        slug                    = "research"
        group                   = "Agents"
        description             = "Private agent"
        publisher               = "CafofoLabs"
        launch_url              = "https://hermes.example.test"
        icon_url                = "https://static.example.test/hermes.png"
        show_in_library         = false
        open_in_new_tab         = true
        policy_engine_mode      = "all"
        backchannel_providers   = [12]
        access_groups           = ["operators"]
        client_type             = "public"
        provider_name           = "Research OIDC"
        authorization_flow_slug = "custom-authorization"
        invalidation_flow_slug  = "custom-invalidation"
        signing_key_name        = "custom-signing"
        redirect_uris           = [{ url = "https://hermes.example.test/auth/callback" }]
      }
    }
  }
  assert {
    condition     = authentik_application.oauth2["hermes"].meta_hide && authentik_application.oauth2["hermes"].open_in_new_tab
    error_message = "Hiding the library card must preserve the OIDC application."
  }
  assert {
    condition     = authentik_application.oauth2["hermes"].name == "Research dashboard" && authentik_application.oauth2["hermes"].group == "Agents" && authentik_application.oauth2["hermes"].policy_engine_mode == "all" && authentik_application.oauth2["hermes"].backchannel_providers == tolist([12])
    error_message = "Application presentation and policy settings must come from the declaration."
  }
  assert {
    condition     = authentik_provider_oauth2.this["hermes"].name == "Research OIDC" && authentik_provider_oauth2.this["hermes"].client_type == "public" && length(data.authentik_flow.oauth2_authorization) == 1 && length(data.authentik_certificate_key_pair.oauth2_signing) == 1
    error_message = "Provider names and existing flow/certificate references must be configurable."
  }
}

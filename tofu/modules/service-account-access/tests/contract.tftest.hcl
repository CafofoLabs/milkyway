mock_provider "authentik" {
  mock_resource "authentik_user" { defaults = { id = "42" } }
}
mock_provider "vault" {}
variables {
  settings = { auth_mount = "service-jwt", slug = "example-services", token_ttl = 300, token_max_ttl = 900 }
  contract = {
    application = "inventory", environment = "dev", deployment = "example",
    profiles    = { application-service = { policies = [] } },
    accounts = {
      svc-inventory-dev = {
        enabled = true, roles = ["application-service"], credential_revision = 1,
        reads   = [{ mount = "secret", path = "apps/inventory/dev", recursive = true }]
      }
      svc-inventory-dev-disabled = {
        enabled = false, roles = ["application-service"], credential_revision = 1, reads = []
      }
    }
  }
}
run "service_contract" {
  command = apply
  assert {
    condition     = authentik_user.service["svc-inventory-dev"].type == "service_account" && authentik_token.bootstrap["svc-inventory-dev"].intent == "app_password" && !authentik_token.bootstrap["svc-inventory-dev"].expiring
    error_message = "Service accounts need individual durable bootstrap credentials."
  }
  assert {
    condition     = vault_jwt_auth_backend_role.service["svc-inventory-dev"].bound_claims["service_account_id"] == "42" && vault_jwt_auth_backend_role.service["svc-inventory-dev"].bound_claims["environment"] == "dev" && vault_jwt_auth_backend_role.service["svc-inventory-dev"].bound_audiences == toset(["example-services"]) && vault_jwt_auth_backend_role.service["svc-inventory-dev"].token_no_default_policy
    error_message = "Bao must validate principal, audience and environment without its default policy."
  }
  assert {
    condition     = strcontains(vault_policy.service["svc-inventory-dev"].policy, "secret/data/apps/inventory/dev/*") && !strcontains(vault_policy.service["svc-inventory-dev"].policy, "list") && !strcontains(vault_policy.service["svc-inventory-dev"].policy, "metadata") && !strcontains(vault_policy.service["svc-inventory-dev"].policy, "create")
    error_message = "Secret access must be read only without implicit listing."
  }
  assert {
    condition     = vault_identity_entity.service["svc-inventory-dev-disabled"].disabled && !contains(keys(authentik_token.bootstrap), "svc-inventory-dev-disabled") && !contains(keys(vault_jwt_auth_backend_role.service), "svc-inventory-dev-disabled") && vault_policy.service["svc-inventory-dev-disabled"].policy == ""
    error_message = "Disabling must remove credentials and login roles and disable the entity."
  }
  assert {
    condition     = !authentik_group.profile["application-service"].is_superuser && startswith(authentik_group.profile["application-service"].name, "mw-example-")
    error_message = "Profiles must use owned scoped groups without IdP administrative privileges."
  }
}
run "second_plan_preserves_credentials" {
  command = plan
  assert {
    condition     = terraform_data.credential_revision["svc-inventory-dev"].output == 1 && length(nonsensitive(authentik_token.bootstrap["svc-inventory-dev"].key)) > 0
    error_message = "An unchanged second plan must preserve credentials."
  }
}
run "credential_revision_is_explicit" {
  command = plan
  variables {
    contract = {
      application = "inventory", environment = "dev", deployment = "example",
      profiles    = { application-service = { policies = [] } },
      accounts    = { svc-inventory-dev = { enabled = true, roles = ["application-service"], credential_revision = 2, reads = [] } }
    }
  }
  assert {
    condition     = endswith(authentik_token.bootstrap["svc-inventory-dev"].identifier, "-r2")
    error_message = "Rotation must be driven by an explicit revision."
  }
}
run "disable_existing_account" {
  command = apply
  variables {
    contract = {
      application = "inventory", environment = "dev", deployment = "example",
      profiles    = { application-service = { policies = [] } },
      accounts = {
        svc-inventory-dev          = { enabled = false, roles = ["application-service"], credential_revision = 2, reads = [] }
        svc-inventory-dev-disabled = { enabled = false, roles = ["application-service"], credential_revision = 1, reads = [] }
      }
    }
  }
  assert {
    condition     = length(authentik_token.bootstrap) == 0 && length(vault_jwt_auth_backend_role.service) == 0 && vault_identity_entity.service["svc-inventory-dev"].disabled && !authentik_user.service["svc-inventory-dev"].is_active
    error_message = "Disabling an existing account must revoke future authentication and remove its bootstrap token."
  }
}
run "two_applications_have_distinct_roles" {
  command = plan
  module { source = "./tests/fixtures/two-apps" }
  assert {
    condition     = output.accounts.inventory["svc-inventory-dev"].role != output.accounts.billing["svc-billing-dev"].role
    error_message = "Applications must own distinct Bao roles even when they share a JWT mount and profile names."
  }
}

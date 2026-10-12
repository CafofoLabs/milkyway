mock_provider "vault" {}

variables {
  oidc = {
    issuer_url            = "https://identity.example.test/application/o/vault/"
    client_id             = "synthetic-test-client"
    client_secret         = "synthetic-test-only"
    allowed_redirect_uris = ["https://vault.example.test/ui/vault/auth/oidc/oidc/callback"]
  }
  kv_mounts = { secrets = { path = "secret" } }
  policies = {
    reader = { name = "application-reader", rules = [{ path = "secret/data/apps/example/*", capabilities = ["read"] }] }
  }
  approles = { reader = { name = "application-reader", token_policies = ["application-reader"] } }
  ssh_ca = {
    roles = { operator = { name = "operator", allowed_users = ["operator"], default_user = "operator" } }
  }
}

run "vault_identity_and_ssh_contract" {
  command = plan
  assert {
    condition     = output.kv_mounts.secrets.data_path == "secret/data"
    error_message = "Consumers must receive the KV v2 data endpoint."
  }
  assert {
    condition     = vault_ssh_secret_backend_role.this["operator"].allowed_users == "operator"
    error_message = "The SSH signing role must preserve its allowed principal."
  }
  assert {
    condition     = vault_approle_auth_backend_role.this["reader"].token_ttl == 3600
    error_message = "Unattended identities must issue short-lived tokens."
  }
}

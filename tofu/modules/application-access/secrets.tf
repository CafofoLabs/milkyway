locals {
  secret_prefix = "apps/${var.slug}"
  policy_name   = "app-${var.slug}"
  secret_policy = <<-EOT
    path "${var.vault_mount}/data/${local.secret_prefix}" {
      capabilities = ["read"]
    }
    path "${var.vault_mount}/data/${local.secret_prefix}/*" {
      capabilities = ["read"]
    }
    path "${var.vault_mount}/metadata/${local.secret_prefix}" {
      capabilities = ["read", "list"]
    }
    path "${var.vault_mount}/metadata/${local.secret_prefix}/*" {
      capabilities = ["read", "list"]
    }
    path "auth/token/lookup-self" {
      capabilities = ["read"]
    }
    path "auth/token/renew-self" {
      capabilities = ["update"]
    }
    path "auth/token/revoke-self" {
      capabilities = ["update"]
    }
  EOT
}

resource "vault_policy" "this" {
  name   = local.policy_name
  policy = local.secret_policy
}

resource "vault_approle_auth_backend_role" "this" {
  backend                 = "approle"
  role_name               = local.policy_name
  bind_secret_id          = true
  token_policies          = [vault_policy.this.name]
  token_no_default_policy = true
  token_type              = "service"
  token_ttl               = 3600
  token_max_ttl           = 14400
  token_explicit_max_ttl  = 14400
  secret_id_ttl           = 0
  secret_id_num_uses      = 0
}

resource "vault_approle_auth_backend_role_secret_id" "this" {
  backend   = "approle"
  role_name = vault_approle_auth_backend_role.this.role_name
}

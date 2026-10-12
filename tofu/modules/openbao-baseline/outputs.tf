output "kv_mounts" {
  description = "KV v2 engines, keyed by local name."
  value = {
    for k, m in vault_mount.kv : k => {
      path     = m.path
      accessor = m.accessor
      # KV v2 puts the data one level down from the mount. Stated here because
      # it is the single most common cause of a policy that grants nothing.
      data_path     = "${m.path}/data"
      metadata_path = "${m.path}/metadata"
    }
  }
}

output "policies" {
  description = "Managed policy names, keyed by local name."
  value       = { for k, p in vault_policy.this : k => p.name }
}

output "ssh_ca" {
  description = <<-EOT
    The SSH certificate authority: the public key hosts must trust, and the
    roles a signature can be requested against. Null when no CA is configured.

    Not sensitive. The public key is meant to be published — it is what every
    host holds in TrustedUserCAKeys, and it grants nothing on its own.
  EOT
  value = var.ssh_ca == null ? null : {
    path       = vault_mount.ssh_ca[0].path
    public_key = trimspace(vault_ssh_secret_backend_ca.this[0].public_key)

    # The same key is served unauthenticated at <vault>/v1/<path>/public_key,
    # which is how Ansible gets it onto a host without holding a credential.
    public_key_path = "/v1/${vault_mount.ssh_ca[0].path}/public_key"

    roles = {
      for key, role in vault_ssh_secret_backend_role.this : key => {
        name          = role.name
        allowed_users = split(",", role.allowed_users)
        default_user  = role.default_user
        ttl           = role.ttl
        max_ttl       = role.max_ttl
        sign_path     = "${vault_mount.ssh_ca[0].path}/sign/${role.name}"
      }
    }
  }
}

output "approles" {
  description = <<-EOT
    Machine identities and their credentials, keyed by local name. Empty when
    none are declared.

    Sensitive in full, not field by field: `secret_id` is a live credential, and
    `role_id` alone is half of one. Read with
    `tofu output -json approles`, and see approle.tf for what it costs.
  EOT
  sensitive   = true
  value = {
    for k, r in vault_approle_auth_backend_role.this : k => {
      name       = r.role_name
      role_id    = r.role_id
      secret_id  = vault_approle_auth_backend_role_secret_id.this[k].secret_id
      login_path = "auth/${local.approle_path}/login"
      policies   = r.token_policies
      token_ttl  = r.token_ttl
    }
  }
}

output "oidc" {
  description = "The OIDC auth method, and how to use it."
  value = {
    path          = vault_jwt_auth_backend.oidc.path
    accessor      = vault_jwt_auth_backend.oidc.accessor
    role          = local.oidc_role_name
    issuer        = var.oidc.issuer_url
    redirect_uris = var.oidc.allowed_redirect_uris
    cli_login     = "bao login -method=oidc -path=${vault_jwt_auth_backend.oidc.path}"
    groups_claim  = var.oidc.groups_claim
    mapped_groups = { for k, g in var.group_roles : g.external_group => g.policies }
  }
}

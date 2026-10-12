# Human authentication, delegated to authentik.
#
# The point of this file: nobody holds an OpenBao credential. Access is decided
# by group membership in the identity provider, revoked by removing someone
# from a group there, and audited in one place. The root token that Ansible
# generated is break-glass only.

locals {
  # Named by a constant rather than by reading it back off the role resource.
  # The backend declares its default role and the role declares its backend, so
  # referencing each other's attributes is a dependency cycle. A literal breaks
  # it: the backend is created naming a role that does not exist yet, which
  # OpenBao accepts because the field is only resolved at login time.
  oidc_role_name = "default"
}

resource "vault_jwt_auth_backend" "oidc" {
  path = var.oidc.path
  type = "oidc"

  oidc_discovery_url = var.oidc.issuer_url
  oidc_client_id     = var.oidc.client_id
  oidc_client_secret = var.oidc.client_secret

  default_role = local.oidc_role_name

  tune {
    default_lease_ttl = "${var.oidc.token_ttl}s"
    max_lease_ttl     = "${var.oidc.token_max_ttl}s"
    token_type        = "default-service"
  }
}

resource "vault_jwt_auth_backend_role" "default" {
  backend   = vault_jwt_auth_backend.oidc.path
  role_name = local.oidc_role_name
  role_type = "oidc"

  # The subject identifier, which authentik keeps stable for a given user even
  # if they change their username or email address.
  user_claim = var.oidc.user_claim

  # What turns group membership into authorisation. The claim has to actually
  # be in the token — that is what the `profile` scope is for.
  groups_claim = var.oidc.groups_claim

  oidc_scopes           = var.oidc.scopes
  allowed_redirect_uris = var.oidc.allowed_redirect_uris

  # Reject a token minted for a different client, even by the same issuer.
  bound_audiences = [var.oidc.client_id]

  token_policies = var.oidc.token_policies
  token_ttl      = var.oidc.token_ttl
  token_max_ttl  = var.oidc.token_max_ttl
}

# --- Group mapping ----------------------------------------------------------
# An "external" identity group is one whose membership OpenBao does not manage:
# it is populated at login time from the groups claim. The alias is the join —
# its name is matched against the claim's values.

resource "vault_identity_group" "external" {
  for_each = var.group_roles

  name     = each.value.external_group
  type     = "external"
  policies = each.value.policies

  depends_on = [vault_policy.this]
}

resource "vault_identity_group_alias" "external" {
  for_each = var.group_roles

  name           = each.value.external_group
  mount_accessor = vault_jwt_auth_backend.oidc.accessor
  canonical_id   = vault_identity_group.external[each.key].id
}

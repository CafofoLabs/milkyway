# Baseline OpenBao configuration: the secret engines and policies that exist
# before any secret is written.

# --- Secret engines ---------------------------------------------------------

resource "vault_mount" "kv" {
  for_each = var.kv_mounts

  path        = each.value.path
  type        = "kv"
  description = each.value.description

  options = {
    version = "2"
  }
}

# --- Policies ---------------------------------------------------------------
# Built from structured rules rather than heredoc HCL so that a typo is a plan
# error instead of a policy that silently grants nothing.

data "vault_policy_document" "this" {
  for_each = var.policies

  dynamic "rule" {
    for_each = each.value.rules
    content {
      path         = rule.value.path
      capabilities = rule.value.capabilities
      description  = rule.value.description
    }
  }
}

resource "vault_policy" "this" {
  for_each = var.policies

  name   = each.value.name
  policy = data.vault_policy_document.this[each.key].hcl

  # Policies naming a mount are useless until it exists, and OpenTofu cannot
  # infer that from a path string.
  depends_on = [vault_mount.kv, vault_mount.ssh_ca]
}

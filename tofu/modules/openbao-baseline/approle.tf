# Machine authentication.
#
# Everything else in this module authenticates a person: oidc.tf delegates to
# authentik, and ssh.tf signs a certificate that expires in an hour. Both flows
# end at a browser, which is the point — nobody holds a credential, and access
# is withdrawn by removing someone from a group.
#
# An AppRole is the deliberate exception, and it exists for one reason: an
# unattended process cannot click a browser. `bao login -method=oidc` opens a
# one-shot listener and waits for a redirect, so a headless session on the
# control node cannot complete it without a human on another machine.
#
# What that costs is honest and worth stating: a role_id and a secret_id are a
# durable credential, they live in this state file and on the control node's
# disk, and unlike a certificate there is nothing that makes them expire on
# their own. This is the one place the platform grants something durable.
#
# So the bounding is done where it can be: by policy. The intended use is a
# role whose policies reach one prefix of one KV mount and nothing else, and in
# particular no capability on the SSH signing path — an AppRole that can call
# `<ssh_ca>/sign/<role>` is an unattended shell on every host, which is exactly
# what ssh.tf exists to avoid.
#
# Two roles break that rule, and both are declared with the argument written out
# rather than left to be inferred. `modules/break-glass` is the credential that
# gets a new control node back in when the OIDC login has not been told about it
# yet, and using it is a signal that something is wrong. The `ops` role in
# tofu/environments/sandbox/main.tf is the opposite: it is the control node's own
# identity, it is meant to be the normal path, and it exists because a browser
# login every hour is not a security control over work nobody is watching — it
# is an interruption that gets the work skipped. Read that policy's comment
# before adding a third.
#
# What is NOT used here, having been considered: `secret_id_bound_cidrs` and
# `token_bound_cidrs`. OpenBao sits behind the reverse proxy and its listener
# does not set `x_forwarded_for_authorized_addrs`, so the address it sees is the
# proxy's on every request. Binding to the control node's tailnet address would
# reject every login; binding to the proxy's would allow everyone. Adding the
# fields would look like a network restriction while being neither, so the
# restriction is the policy above and the TTL below.

locals {
  # The conventional mount path, and the one `bao write auth/approle/login`
  # assumes when nothing says otherwise. Not configurable: a second path would
  # buy nothing and every consumer would have to be told about it.
  approle_path = "approle"
}

resource "vault_auth_backend" "approle" {
  # No roles, no auth method. The mount is not free — it is one more way in —
  # so an environment that declares no AppRole does not get one.
  count = length(var.approles) > 0 ? 1 : 0

  type = "approle"
  path = local.approle_path

  description = "Machine identities. Humans use OIDC — see oidc.tf."
}

resource "vault_approle_auth_backend_role" "this" {
  for_each = var.approles

  backend   = vault_auth_backend.approle[0].path
  role_name = each.value.name

  token_policies = each.value.token_policies

  # In seconds, and numbers rather than duration strings, for the same reason
  # ssh.tf gives: the API answers in seconds, so `"1h"` reads back as `"3600"`
  # and every subsequent plan proposes changing it back.
  token_ttl     = each.value.token_ttl
  token_max_ttl = each.value.token_max_ttl

  # A short token TTL is most of what makes this bearable. The secret_id is
  # durable, but what it mints is not: a token that leaks out of a process is
  # useless within the hour, and nothing has to be revoked.
  secret_id_ttl = each.value.secret_id_ttl

  # A policy naming a mount grants nothing until the policy exists, and
  # OpenTofu cannot infer that from a list of strings.
  depends_on = [vault_policy.this]
}

# The credential itself. Issued here rather than out of band so that it is one
# apply and not a documented sequence — and so that rotating it is
# `tofu apply -replace`, which is a command rather than a procedure.
#
# This is what puts a live secret in the state file. The state is gitignored and
# local to the control node, which is also where the credential is going to end
# up anyway; the alternative is issuing it by hand with the root token, which
# moves the secret out of one file the control node holds and into another.
resource "vault_approle_auth_backend_role_secret_id" "this" {
  for_each = var.approles

  backend   = vault_auth_backend.approle[0].path
  role_name = vault_approle_auth_backend_role.this[each.key].role_name
}

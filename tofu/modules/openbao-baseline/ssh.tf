# SSH access, issued as certificates rather than installed as keys.
#
# The problem this replaces: a public key in `authorized_keys` is a permanent
# grant. It is copied per host, revoked per host, and nothing on the host knows
# who it belongs to or when it should stop working. Removing someone means
# finding every file it reached, which is exactly the kind of task that is
# quietly never finished.
#
# With a certificate authority the host trusts one public key — this one — and
# accepts anything it has signed. Nobody's key is installed anywhere. Access is
# a signing request the vault authorises against the same authentik group
# membership that grants everything else, and the certificate it returns is
# valid for an hour.
#
# That last part is the revocation story, and it is worth being explicit that
# there is no other one: OpenSSH has no way to ask whether a certificate is
# still good. A signed certificate is valid until it expires, full stop. Short
# TTLs are therefore not a hardening tweak, they are the mechanism. Removing
# someone from the group stops the *next* signature; the one they are holding
# runs out on its own.

locals {
  # `count` on the mount and the CA, `for_each` on the roles. Written as a
  # number and a map rather than repeating the conditional at every use.
  ssh_ca_count = var.ssh_ca == null ? 0 : 1
  ssh_ca_roles = var.ssh_ca == null ? {} : var.ssh_ca.roles
}

resource "vault_mount" "ssh_ca" {
  count = local.ssh_ca_count

  path        = var.ssh_ca.path
  type        = "ssh"
  description = "SSH client certificate authority"
}

resource "vault_ssh_secret_backend_ca" "this" {
  count = local.ssh_ca_count

  backend = vault_mount.ssh_ca[0].path

  # The vault generates the key pair itself, so the private half is created
  # inside the vault and never travels. Importing an existing CA key would mean
  # the key existing somewhere else first, which is the thing worth avoiding.
  #
  # Note that this resource is also where the CA key would be *rotated*, and
  # rotation is not free: every host trusts the public key by content, so a new
  # key locks out every certificate signed by the old one until Ansible has run
  # everywhere. Not a problem to solve here, but a reason not to taint this
  # resource casually.
  generate_signing_key = true
  key_type             = var.ssh_ca.key_type
}

resource "vault_ssh_secret_backend_role" "this" {
  for_each = local.ssh_ca_roles

  backend = vault_mount.ssh_ca[0].path
  name    = each.value.name

  key_type                = "ca"
  allow_user_certificates = true

  # `allowed_users` bounds which principals may be requested; `default_user` is
  # what a request that names none gets. The principal has to match the Unix
  # account being logged into — that is the whole authorisation check sshd
  # performs, once it trusts the signature.
  allowed_users = join(",", each.value.allowed_users)
  default_user  = each.value.default_user

  ttl     = each.value.ttl
  max_ttl = each.value.max_ttl

  # Extensions are opt-in per certificate. Without `permit-pty` there is no
  # interactive shell — a certificate that logs in and immediately hangs up is
  # the usual first symptom of getting this wrong. Everything absent from this
  # list stays absent: no port forwarding, no agent forwarding, no X11.
  default_extensions = { for extension in each.value.extensions : extension => "" }
  allowed_extensions = join(",", each.value.extensions)

  # sshd logs the key ID on every accepted certificate, so this string is what
  # turns "someone logged in as thiago" in auth.log into a named person and a
  # specific signing request. `token_display_name` resolves to the identity the
  # vault authenticated, which for an OIDC login is the authentik account.
  key_id_format = "{{role_name}}-{{token_display_name}}-{{public_key_hash}}"

  # Backdate the validity window. Certificates are checked against the host's
  # clock, not the vault's, and a host a few seconds ahead would otherwise
  # reject a certificate issued the moment before.
  #
  # Seconds, unsuffixed, for the same reason as the TTLs above: `"30s"` applies
  # and reads back as `"30"`, and every plan then offers to change it back.
  not_before_duration = "30"
}

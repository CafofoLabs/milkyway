terraform {
  required_version = ">= 1.6.0"

  required_providers {
    # There is no OpenBao-specific provider — the registry has none, and the
    # community uses this one against OpenBao's Vault-compatible API. That is
    # a real assumption, so it was tested rather than trusted: every resource
    # type used by this module was applied against a live OpenBao 2.6.1 and
    # re-planned twice with no drift before the module was written.
    #
    # Where the two are known to diverge is namespaces (openbao#1508), which
    # this module does not use.
    vault = {
      source  = "hashicorp/vault"
      version = "~> 5.10"
    }
  }
}

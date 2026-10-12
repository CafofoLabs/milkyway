variable "slug" {
  description = "Globally unique application slug; also fixes its OpenBao prefix to apps/<slug>."
  type        = string
  validation {
    condition     = can(regex("^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$", var.slug))
    error_message = "slug must be a lowercase DNS label starting with a letter, without wildcard or path characters."
  }
}

variable "name" {
  description = "Application display name in the Authentik dashboard."
  type        = string
  validation {
    condition     = trimspace(var.name) != ""
    error_message = "name must not be empty."
  }
}

variable "identity_url" {
  description = "Existing Authentik HTTPS origin, without a path or trailing slash."
  type        = string
  validation {
    condition     = can(regex("^https://[A-Za-z0-9.-]+(:[0-9]+)?$", var.identity_url))
    error_message = "identity_url must be an HTTPS origin with no path, credentials or trailing slash."
  }
}

variable "launch_url" {
  description = "Private HTTPS application URL opened by the Authentik dashboard."
  type        = string
  validation {
    condition     = can(regex("^https://[A-Za-z0-9.-]+(:[0-9]+)?([/?][^\\s#]*)?$", var.launch_url))
    error_message = "launch_url must be an HTTPS URL without userinfo, whitespace or a fragment."
  }
}

variable "redirect_uris" {
  description = "Exact HTTPS OIDC authorization callback URLs implemented by the application."
  type        = list(string)
  validation {
    condition     = length(var.redirect_uris) > 0 && length(distinct(var.redirect_uris)) == length(var.redirect_uris) && alltrue([for uri in var.redirect_uris : can(regex("^https://[A-Za-z0-9.-]+(:[0-9]+)?([/?][^\\s#]*)?$", uri)) && !strcontains(uri, "*")])
    error_message = "redirect_uris requires unique exact HTTPS callback URLs without fragments or wildcards."
  }
}

variable "access_group_ids" {
  description = "Existing Authentik group UUIDs permitted to launch and authenticate to this app."
  type        = list(string)
  validation {
    condition     = length(var.access_group_ids) > 0 && length(distinct(var.access_group_ids)) == length(var.access_group_ids) && alltrue([for id in var.access_group_ids : can(regex("^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$", id))])
    error_message = "access_group_ids requires at least one unique existing group UUID; unrestricted applications are not allowed."
  }
}

variable "vault_mount" {
  description = "Existing OpenBao KV v2 mount; the module does not create or change mounts."
  type        = string
  default     = "secret"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*$", var.vault_mount))
    error_message = "vault_mount must be one lowercase mount path segment without wildcard characters."
  }
}

variable "signing_key_name" {
  description = "Existing Authentik signing key maintained by the infrastructure baseline."
  type        = string
  default     = "authentik Self-signed Certificate"
}

variable "authorization_flow_slug" {
  description = "Existing authorization flow maintained by the infrastructure baseline."
  type        = string
  default     = "default-provider-authorization-implicit-consent"
}

variable "invalidation_flow_slug" {
  description = "Existing logout flow maintained by the infrastructure baseline."
  type        = string
  default     = "default-provider-invalidation-flow"
}

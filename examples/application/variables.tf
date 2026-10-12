variable "slug" {
  type        = string
  description = "Unique application slug."
}
variable "name" {
  type        = string
  description = "Dashboard display name."
}
variable "identity_url" {
  type        = string
  description = "Existing Authentik HTTPS origin."
}
variable "vault_url" {
  type        = string
  description = "Existing OpenBao HTTPS origin."
}
variable "launch_url" {
  type        = string
  description = "The consumer application's private HTTPS URL."
}
variable "redirect_uris" {
  type        = list(string)
  description = "Exact authorization callback URLs implemented by the app."
}
variable "access_group_ids" {
  type        = list(string)
  description = "Existing infrastructure group UUIDs; the app does not create groups."
}
variable "state_encryption_passphrase" {
  type        = string
  sensitive   = true
  description = "Supplied through TF_VAR_state_encryption_passphrase, kept recoverable outside OpenBao."
}

variable "authentik_api_token" {
  type        = string
  sensitive   = true
  description = "Supplied through TF_VAR_authentik_api_token by trusted provisioning automation."
}

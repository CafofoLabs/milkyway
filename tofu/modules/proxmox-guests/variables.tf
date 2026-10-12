variable "node_name" {
  description = "Default Proxmox node for guests without an explicit node."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", var.node_name))
    error_message = "node_name must be a lowercase DNS label."
  }
}

variable "datastore_id" {
  description = "Existing datastore for cloned root and cloud-init disks."
  type        = string
}

variable "bridge" {
  description = "Existing Proxmox bridge attached to the isolated lab network."
  type        = string
}

variable "pool_id" {
  description = "Existing resource pool used to scope the API identity."
  type        = string
}

variable "template_id" {
  description = "Existing, prepared Debian cloud template VM ID on node_name."
  type        = number

  validation {
    condition     = var.template_id >= 100 && var.template_id <= 999999999 && floor(var.template_id) == var.template_id
    error_message = "template_id must be an integer Proxmox VM ID from 100 to 999999999."
  }
}

variable "operator" {
  description = "Bootstrap operator and public key path; OpenTofu reads the public file at runtime."
  type = object({
    name            = string
    public_key_file = string
  })

  validation {
    condition     = can(regex("^[a-z_][a-z0-9_-]{0,31}$", var.operator.name)) && var.operator.name != "root" && trimspace(var.operator.public_key_file) != ""
    error_message = "operator requires a non-root Linux username and a public key file path."
  }
}

variable "network" {
  description = "Static IPv4 guest network; addresses must be reserved outside the DHCP pool."
  type = object({
    prefix_length = number
    gateway       = string
    nameservers   = list(string)
    search_domain = optional(string)
  })

  validation {
    condition     = var.network.prefix_length >= 8 && var.network.prefix_length <= 30 && floor(var.network.prefix_length) == var.network.prefix_length && can(cidrnetmask("${var.network.gateway}/32")) && length(var.network.nameservers) > 0 && alltrue([for address in var.network.nameservers : can(cidrnetmask("${address}/32"))])
    error_message = "network requires an IPv4 gateway, IPv4 DNS servers and an integer prefix from 8 to 30."
  }
}

variable "hosts" {
  description = "Infrastructure VMs keyed by consumer-chosen hostname; application guests are outside this initial module."
  type = map(object({
    vm_id         = number
    node          = optional(string)
    role          = string
    address       = string
    memory_mb     = number
    vcpus         = number
    disk_gb       = number
    cpu_type      = optional(string, "x86-64-v2-AES")
    startup_order = optional(number, 30)
  }))

  validation {
    condition     = alltrue([for name, host in var.hosts : can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", name)) && contains(["identity", "vault", "platform"], host.role)])
    error_message = "Each hostname must be a lowercase DNS label and role must be identity, vault or platform."
  }

  validation {
    condition     = alltrue([for host in var.hosts : host.node == null ? true : can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", host.node))])
    error_message = "An explicit guest node must be a lowercase DNS label."
  }

  validation {
    condition     = length(distinct([for host in var.hosts : host.vm_id])) == length(var.hosts) && alltrue([for host in var.hosts : host.vm_id >= 100 && host.vm_id <= 999999999 && floor(host.vm_id) == host.vm_id && host.vm_id != var.template_id])
    error_message = "Guest VM IDs must be unique integers from 100 to 999999999 and differ from template_id."
  }

  validation {
    condition     = length(distinct([for host in var.hosts : host.address])) == length(var.hosts) && alltrue([for host in var.hosts : can(cidrnetmask("${host.address}/32"))])
    error_message = "Guest addresses must be unique bare IPv4 addresses."
  }

  validation {
    condition     = alltrue([for host in var.hosts : host.memory_mb >= 1024 && floor(host.memory_mb) == host.memory_mb && host.vcpus >= 1 && host.vcpus <= 64 && floor(host.vcpus) == host.vcpus && host.disk_gb >= 8 && floor(host.disk_gb) == host.disk_gb && host.startup_order >= 0 && floor(host.startup_order) == host.startup_order && trimspace(host.cpu_type) != ""])
    error_message = "Guest sizes and startup order must be whole numbers: RAM >=1024 MiB, CPUs 1..64, disk >=8 GiB, order >=0; CPU type is required."
  }

  validation {
    condition = alltrue([for host in var.hosts : try(
      cidrhost("${host.address}/${var.network.prefix_length}", 0) == cidrhost("${var.network.gateway}/${var.network.prefix_length}", 0) &&
      host.address != var.network.gateway &&
      host.address != cidrhost("${host.address}/${var.network.prefix_length}", 0) &&
      host.address != cidrhost("${host.address}/${var.network.prefix_length}", -1), false
    )])
    error_message = "Guest addresses must be usable addresses in the gateway subnet, excluding the gateway."
  }
}

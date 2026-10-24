terraform {
  required_version = ">= 1.10.0, < 2.0.0"
  required_providers { proxmox = { source = "bpg/proxmox", version = "0.116.0" } }
}

variable "node" { type = string }
variable "pool" { type = string }
variable "datastore" { type = string }
variable "bridge" { type = string }
variable "template_id" { type = number }
variable "operator" {
  type = string
  validation {
    condition     = can(regex("^[a-z_][a-z0-9_-]{0,31}$", var.operator)) && var.operator != "root"
    error_message = "The bootstrap operator must be a non-root Linux account."
  }
}
variable "public_key_file" { type = string }
variable "nameservers" { type = list(string) }
variable "allowed_nodes" {
  type = set(string)
  validation {
    condition     = length(var.allowed_nodes) > 0
    error_message = "Explicitly authorize placement nodes."
  }
}
variable "hosts" {
  type = map(object({ node = string, vm_id = number, vcpus = number, memory_mb = number, disk_gb = number, cpu_type = optional(string, "x86-64-v3") }))
  validation {
    condition     = alltrue([for host in var.hosts : contains(["x86-64-v3", "host"], host.cpu_type)])
    error_message = "Native VM CPU type must be x86-64-v3 or host."
  }
  validation {
    condition     = alltrue([for name, host in var.hosts : can(regex("^[a-z][a-z0-9-]{0,47}$", name)) && contains(var.allowed_nodes, host.node) && host.vm_id >= 100 && host.vm_id <= 999999999 && floor(host.vm_id) == host.vm_id && host.vm_id != var.template_id && host.vcpus >= 1 && host.vcpus <= 64 && floor(host.vcpus) == host.vcpus && host.memory_mb >= 1024 && floor(host.memory_mb) == host.memory_mb && host.disk_gb >= 8 && floor(host.disk_gb) == host.disk_gb]) && length(distinct([for h in var.hosts : h.vm_id])) == length(var.hosts)
    error_message = "Guests require authorized nodes, unique IDs and valid whole-number sizes."
  }
}

resource "proxmox_virtual_environment_vm" "this" {
  for_each            = var.hosts
  name                = each.key
  description         = "Native Linux application VM"
  node_name           = each.value.node
  vm_id               = each.value.vm_id
  pool_id             = var.pool
  tags                = ["milkyway", "native-linux"]
  on_boot             = true
  started             = true
  protection          = true
  reboot_after_update = false
  scsi_hardware       = "virtio-scsi-single"
  boot_order          = ["scsi0"]
  clone {
    node_name    = var.node
    vm_id        = var.template_id
    datastore_id = var.datastore
    full         = true
    retries      = 3
  }
  cpu {
    cores = each.value.vcpus
    type  = each.value.cpu_type
  }
  memory {
    dedicated = each.value.memory_mb
    floating  = 0
  }
  disk {
    datastore_id = var.datastore
    interface    = "scsi0"
    size         = each.value.disk_gb
    file_format  = "raw"
    cache        = "none"
    aio          = "io_uring"
    discard      = "on"
    iothread     = true
    ssd          = true
  }
  initialization {
    datastore_id = var.datastore
    dns { servers = var.nameservers }
    ip_config {
      ipv4 { address = "dhcp" }
    }
    user_account {
      username = var.operator
      keys     = [trimspace(file(var.public_key_file))]
    }
  }
  network_device {
    bridge   = var.bridge
    model    = "virtio"
    firewall = true
  }
  agent {
    enabled = true
    trim    = true
    wait_for_ip { disabled = true }
  }
  operating_system { type = "l26" }
  lifecycle { prevent_destroy = true }
}

locals {
  operator_public_key = trimspace(file(pathexpand(var.operator.public_key_file)))
}

resource "proxmox_virtual_environment_vm" "this" {
  for_each = var.hosts

  name                = each.key
  description         = "MilkyWay infrastructure: ${each.value.role}"
  node_name           = var.node_name
  vm_id               = each.value.vm_id
  pool_id             = var.pool_id
  tags                = sort(["milkyway", each.value.role])
  on_boot             = true
  started             = true
  protection          = true
  reboot_after_update = false
  scsi_hardware       = "virtio-scsi-single"
  boot_order          = ["scsi0"]

  clone {
    vm_id        = var.template_id
    datastore_id = var.datastore_id
    full         = true
    retries      = 3
  }

  agent {
    enabled = true
    timeout = "5m"
    trim    = true

    wait_for_ip {
      ipv4 = true
    }
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
    datastore_id = var.datastore_id
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
    datastore_id = var.datastore_id

    dns {
      servers = var.network.nameservers
      domain  = var.network.search_domain
    }

    ip_config {
      ipv4 {
        address = "${each.value.address}/${var.network.prefix_length}"
        gateway = var.network.gateway
      }
    }

    user_account {
      username = var.operator.name
      keys     = [local.operator_public_key]
    }
  }

  network_device {
    bridge   = var.bridge
    model    = "virtio"
    firewall = true
  }

  operating_system {
    type = "l26"
  }

  startup {
    order      = each.value.startup_order
    up_delay   = 30
    down_delay = 60
  }

  lifecycle {
    prevent_destroy = true

    precondition {
      condition     = can(regex("^ssh-ed25519 [A-Za-z0-9+/]+={0,2}( .*|)$", local.operator_public_key))
      error_message = "operator.public_key_file must contain one Ed25519 public key; private keys are never accepted."
    }
  }
}

mock_provider "proxmox" {}
variables {
  node            = "test-node"
  allowed_nodes   = ["test-node"]
  datastore       = "local-lvm"
  pool            = "test-pool"
  bridge          = "vmbr0"
  template_id     = 9000
  operator        = "nimbus"
  public_key_file = "tests/operator.pub"
  nameservers     = ["192.0.2.1"]
  hosts = {
    test-agent = { node = "test-node", vm_id = 105, vcpus = 4, memory_mb = 8192, disk_gb = 50 }
  }
}
run "native_vm" {
  command = plan
  assert {
    condition     = proxmox_virtual_environment_vm.this["test-agent"].cpu[0].type == "x86-64-v3"
    error_message = "Existing maps must retain their default CPU model."
  }
  assert {
    condition     = proxmox_virtual_environment_vm.this["test-agent"].protection && !proxmox_virtual_environment_vm.this["test-agent"].reboot_after_update && proxmox_virtual_environment_vm.this["test-agent"].clone[0].full
    error_message = "Native guests require full clones, deletion protection and explicit reboots."
  }
  assert {
    condition     = proxmox_virtual_environment_vm.this["test-agent"].initialization[0].ip_config[0].ipv4[0].address == "dhcp" && proxmox_virtual_environment_vm.this["test-agent"].vm_id == 105
    error_message = "Creation must preserve the requested identity and DHCP bootstrap."
  }
}
run "host_cpu" {
  command = plan
  variables {
    hosts = {
      test-agent = { node = "test-node", vm_id = 105, vcpus = 4, memory_mb = 8192, disk_gb = 50, cpu_type = "host" }
    }
  }
  assert {
    condition     = proxmox_virtual_environment_vm.this["test-agent"].cpu[0].type == "host"
    error_message = "The selected host CPU model must reach the Proxmox resource."
  }
}
run "reject_cpu_type" {
  command = plan
  variables {
    hosts = {
      test-agent = { node = "test-node", vm_id = 105, vcpus = 4, memory_mb = 8192, disk_gb = 50, cpu_type = "unsupported" }
    }
  }
  expect_failures = [var.hosts]
}
run "reject_placement" {
  command = plan
  variables { allowed_nodes = ["another-node"] }
  expect_failures = [var.hosts]
}
run "reject_duplicate_ids" {
  command = plan
  variables {
    hosts = {
      first  = { node = "test-node", vm_id = 105, vcpus = 4, memory_mb = 8192, disk_gb = 50 }
      second = { node = "test-node", vm_id = 105, vcpus = 2, memory_mb = 4096, disk_gb = 30 }
    }
  }
  expect_failures = [var.hosts]
}

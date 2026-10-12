mock_provider "proxmox" {}

variables {
  node_name    = "test-node"
  datastore_id = "local-lvm"
  bridge       = "vmbr0"
  pool_id      = "test-pool"
  template_id  = 9000
  operator = {
    name            = "operator"
    public_key_file = "tests/operator.pub"
  }
  network = {
    prefix_length = 24
    gateway       = "192.0.2.1"
    nameservers   = ["192.0.2.1"]
  }
  hosts = {
    test-idp = {
      vm_id         = 101
      role          = "identity"
      address       = "192.0.2.20"
      memory_mb     = 4096
      vcpus         = 4
      disk_gb       = 40
      startup_order = 10
    }
  }
}

run "infrastructure_contract" {
  command = plan

  assert {
    condition     = output.hosts["test-idp"].ansible_host == "192.0.2.20" && output.hosts["test-idp"].role == "identity"
    error_message = "The inventory contract must preserve the declared address and role."
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this["test-idp"].protection && !proxmox_virtual_environment_vm.this["test-idp"].reboot_after_update
    error_message = "Stateful guests must be protected and must not reboot automatically during updates."
  }

  assert {
    condition     = proxmox_virtual_environment_vm.this["test-idp"].cpu[0].type == "x86-64-v2-AES" && proxmox_virtual_environment_vm.this["test-idp"].clone[0].full
    error_message = "Guests must use full clones and the explicit migration-compatible CPU default."
  }
}

run "reject_unrelated_workloads" {
  command = plan
  variables {
    hosts = {
      test-app = { vm_id = 102, role = "application", address = "192.0.2.21", memory_mb = 2048, vcpus = 2, disk_gb = 20 }
    }
  }
  expect_failures = [var.hosts]
}

run "reject_gateway_address" {
  command = plan
  variables {
    hosts = {
      test-bao = { vm_id = 102, role = "vault", address = "192.0.2.1", memory_mb = 2048, vcpus = 2, disk_gb = 20 }
    }
  }
  expect_failures = [var.hosts]
}

run "reject_duplicate_vm_ids" {
  command = plan
  variables {
    hosts = {
      test-idp = { vm_id = 101, role = "identity", address = "192.0.2.20", memory_mb = 4096, vcpus = 4, disk_gb = 40 }
      test-bao = { vm_id = 101, role = "vault", address = "192.0.2.21", memory_mb = 2048, vcpus = 2, disk_gb = 20 }
    }
  }
  expect_failures = [var.hosts]
}

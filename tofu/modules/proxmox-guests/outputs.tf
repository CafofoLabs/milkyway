output "hosts" {
  description = "Non-secret VM facts for the consumer's Ansible inventory; runtime tailnet addresses are discovered after enrollment."
  value = {
    for name, vm in proxmox_virtual_environment_vm.this : name => {
      vm_id        = vm.vm_id
      node_name    = vm.node_name
      ansible_host = var.hosts[name].address
      ansible_user = var.operator.name
      role         = var.hosts[name].role
      memory_mb    = var.hosts[name].memory_mb
      vcpus        = var.hosts[name].vcpus
      disk_gb      = var.hosts[name].disk_gb
    }
  }
}

output "template_id" {
  description = "Template selected for guest creation; template provisioning is owned by the consumer bootstrap."
  value       = var.template_id
}

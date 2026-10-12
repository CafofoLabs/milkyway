# Proxmox infrastructure guests

`tofu/modules/proxmox-guests` creates the initial identity, vault and shared-platform VMs. It reuses Jarvis's declarative guest map, bootstrap operator, static network and inventory output contract. The resource implementation uses the Proxmox API instead of libvirt. It does not install services or manage application workloads.

## Requirements and ownership

- OpenTofu 1.10 or newer, with `bpg/proxmox` pinned to `0.116.0`.
- An existing Proxmox VE 9 node, resource pool, datastore and network bridge.
- A prepared Debian cloud template on that same node: a root disk at `scsi0`, `virtio-scsi-single`, cloud-init disk, QEMU guest agent installation and activation through the template vendor-data, serial console support, unique per-clone SSH host keys and machine IDs. SSH passwords and root SSH login must be disabled; the cloud-init operator must receive passwordless sudo. The template must disable automatic cloud-init upgrades, which are managed explicitly by Ansible.
- The consumer supplies a scoped API provider with verified TLS, an encrypted and locking state backend independent of OpenBao, and a local operator public-key file. The module never reads the private key or stores provider credentials in outputs.

The consumer owns template preparation, credentials, provider/backend configuration, VM names, addresses and service placement. This module owns only the guest VMs it declares. Existing Jarvis machines and state are not imported. A provider dependency lock belongs to the consumer root, where it must be committed.

## Inputs

| Input | Meaning |
| --- | --- |
| `node_name`, `datastore_id`, `bridge`, `pool_id` | Existing Proxmox resources. |
| `template_id` | Existing prepared template, pinned by its VM ID. |
| `operator` | Non-root `name` and local `public_key_file` path. Only Ed25519 public keys are accepted. |
| `network` | IPv4 `prefix_length`, `gateway`, `nameservers`, optional `search_domain`. |
| `hosts` | Map keyed by hostname: `vm_id`, `role`, `address`, `memory_mb`, `vcpus`, `disk_gb`, optional `cpu_type` and `startup_order`. |

Roles are `identity`, `vault` and `platform`. Guest IDs and IPv4 addresses must be unique; addresses must belong to the gateway subnet and exclude its network, broadcast and gateway addresses. Reserve them outside the DHCP pool. Defaults are `x86-64-v2-AES` for the CPU and `30` for startup order; the consumer chooses an earlier order for identity and vault. CPU compatibility across future nodes must be checked before migration.

Each VM receives a full clone, a raw root disk, fixed RAM, a VirtIO network interface with Proxmox firewall support, static cloud-init networking, the bootstrap public key and QEMU-agent IPv4 readiness checks. Proxmox firewall support alone does not install filtering rules; the baseline must configure them before service exposure. Startup delays sequence boot attempts, not service health.

## Execution and outputs

Run the consumer's Makefile plan/apply targets from Nimbus. Do not execute this module as an independent root against a live node: it deliberately has no provider or backend configuration.

1. Prepare and verify the template through the consumer's Ansible bootstrap.
2. Initialize the consumer root and review its saved OpenTofu plan.
3. Apply that approved plan, then wait for cloud-init and independently verify SSH host identity before Ansible connects.
4. Configure guest baselines and deploy services through Ansible.
5. Repeat the OpenTofu plan; without drift it must show no changes.

`hosts` exports each guest's VM ID, Proxmox node, bootstrap LAN address, operator, logical role and sizing. Ansible inventory generation consumes that map. No credentials or public-key contents are outputs. Tailnet names and addresses are discovered after enrollment. `template_id` identifies the selected creation template.

## Changes, destruction and recovery

Both OpenTofu `prevent_destroy` and Proxmox VM protection are enabled. Replacement and deletion fail instead of silently destroying service data. There are no libvirt-style replacement triggers tied to cloud-init contents. Automatic provider reboots on updates are disabled; an update that requires shutdown fails and must be scheduled explicitly. Disk shrink is unsupported.

Cloud-init settings describe first boot. Changing the declared address, operator or key on a running guest is not proof that the guest OS adopted the change. Review the plan and use the corresponding Ansible procedure; verify reachability before removing old access. Changing the template ID may require replacement and is blocked by protection. Do not remove protection or state to make an ordinary update succeed. Destruction or replacement requires a separately approved data-preservation and recovery procedure.

If an apply fails, retain state and inspect the plan before retrying; do not create the same VM manually. State recovery must be possible without Authentik or OpenBao. The consumer keeps the state encryption recovery material outside the services managed here.

## Verification

The module's mock-provider tests validate the inventory contract and reject unsupported roles, gateway addresses and duplicate VM IDs without connecting to Proxmox:

```sh
cd tofu/modules/proxmox-guests
tofu init -backend=false
tofu validate
tofu test
```

These checks validate provider schema and plans. They do not prove real cloning, first-boot configuration, network isolation, service health, reboot recovery or an empty repeat plan on Mercury. Those checks belong to the first consumer deployment.

## Sources

- [Pinned provider VM schema](https://github.com/bpg/terraform-provider-proxmox/blob/v0.116.0/docs/resources/virtual_environment_vm.md)
- [Pinned provider requirements and authentication](https://github.com/bpg/terraform-provider-proxmox/blob/v0.116.0/docs/index.md)
- [Proxmox cloud-init support](https://pve.proxmox.com/pve-docs/qm.1.html#qm_cloud_init)

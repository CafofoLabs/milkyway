# Proxmox cloud template

The `proxmox_template` Ansible role prepares one unbooted Debian 13 cloud template for the infrastructure VMs. OpenTofu owns clones; this role owns the reusable creation template. No services or containers run on the Proxmox host.

## Inputs

| Variable | Default / purpose |
| --- | --- |
| `proxmox_template_id` | `9000`, unique across the cluster. |
| `proxmox_pool` | `nimbus`, existing resource pool owned by the consumer. |
| `proxmox_datastore` | `local-lvm`, target for root and cloud-init disks. |
| `proxmox_bridge` | `vmbr0`, existing lab bridge. |
| `proxmox_node_name` | Gathered `ansible_hostname`; pass explicitly when facts are disabled. |
| `proxmox_template_snippet_datastore` | `local`, existing directory-backed storage for vendor-data. |
| `proxmox_template_image_version` | Official immutable Debian build `20261001-2618`. |
| `proxmox_template_image_url` | Debian 13 genericcloud AMD64 QCOW2 URL for that build. |
| `proxmox_template_image_sha512` | Verified SHA512 pinned in role defaults. |

Nimbus supplies deployment names, pool and placement. The role runs through verified bootstrap SSH with root privileges on Proxmox. No API token or operator private/public key is an input to this role. The OpenTofu guest module supplies the operator account and public key separately.

## Execution

1. Inspect cluster VM IDs and refuse an ID belonging to a container or another node.
2. If the ID exists, require a completed template with the expected image/vendor-data digest marker and matching storage, bridge and cloud-init configuration. A partial or different VM stops the run before template changes.
3. Enable `snippets` on the selected directory storage while preserving every existing content type.
4. Persist vendor-data under an immutable, digest-derived filename.
5. Download the immutable official image and check its SHA512 before import.
6. Create an unbooted VM in the consumer pool, import its `scsi0` root disk, attach cloud-init at `ide2`, enable the QEMU agent, add a serial console and disable automatic cloud-init upgrades.
7. Convert that VM to a template and verify its final configuration.

The vendor-data installs and starts the QEMU guest agent on each clone's first boot. It disables root/password SSH, regenerates SSH host keys per instance and reloads SSH after applying the configuration. It does not define `users` or replace Proxmox-generated user-data, so OpenTofu's selected operator and authorized public key remain effective. Debian's default cloud user configuration supplies sudo privileges.

The provider can wait for agent-reported IPv4 after the package installation finishes. Guest networking must have outgoing access to Debian package repositories at first boot. Failure to install the agent must stop provisioning; it is not a reason to disable SSH host verification. The consumer can obtain public host keys through the authenticated Proxmox QEMU-agent API before first SSH access.

## Repeated runs and recovery

A matching completed template is reused without download, cloning, deletion or recreation. The vendor-data file is restored if it has drifted, and snippet support remains enabled. Image and vendor-data pins are part of the template identity; changing either requires an explicitly chosen new template ID and a reviewed consumer plan.

A failed creation leaves an unbooted candidate for inspection. A subsequent run refuses that incomplete ID. There is no automatic deletion, disk replacement or orphan cleanup. Approve recovery separately after inspecting the candidate and preserving anything needed. The template and its vendor-data must remain available while guests refer to them; future cross-node use requires an explicit storage/template distribution plan.

Check mode performs read-only inspection and reports supported changes; it does not prove that a new image imports or a guest boots. A normal run requires the pre-existing pool, bridge and datastores. Bootstrap is not a full cluster or availability implementation.

## Verification

Syntax validation and offline checks cover task syntax and vendor-data structure. Deployment acceptance additionally requires: the correct template marker, successful clone boot, a running QEMU agent, distinct SSH host keys and machine IDs across clones, key-only operator access, root SSH denial, and a repeat run without VM changes. No real template or clone is claimed to be verified by local syntax checks.

## Sources

- [Immutable Debian image build and SHA512 manifest](https://cloud.debian.org/images/cloud/trixie/20261001-2618/)
- [Proxmox cloud-init template procedure](https://github.com/proxmox/pve-docs/blob/master/qm-cloud-init.adoc)
- [Proxmox generated user-data and vendor-data handling](https://github.com/proxmox/qemu-server/blob/master/src/PVE/QemuServer/Cloudinit.pm)
- [Cloud-init module reference](https://docs.cloud-init.io/en/latest/reference/modules.html)

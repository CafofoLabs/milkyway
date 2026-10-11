# Proxmox hostname

This operation corrects the installer hostname before any workload or cluster exists. Desired names and the management IPv4 address come from the consumer inventory; the framework contains no environment naming convention.

## Usage

```sh
make host-rename-plan INVENTORY=/path/to/host.toml PREVIOUS_HOSTNAME=old-name
make host-rename INVENTORY=/path/to/host.toml PREVIOUS_HOSTNAME=old-name
```

The script uses trusted, noninteractive SSH, verifies Proxmox VE 9, an empty standalone node, expected old/new identity, and no node-specific storage restrictions. Unexpected node files, guest configurations, destination collisions, or additional nodes stop the operation. Select the existing private-key path with `MILKYWAY_SSH_IDENTITY_FILE` (the file is passed directly to SSH, never read by the framework), or configure the identity through SSH; credentials never belong in inventory.

The first apply backs up hostname, hosts, and Postfix configuration in a root-only directory under `/var/backups/milkyway-hostname/OLD`, then changes `/etc/hostname`, the matching IPv4 entry in `/etc/hosts` (preserving its domain suffix), and Postfix's hostname. It does not change network addresses, SSH host keys, DNS records, or firewall policy.

When `reboot_required` is true, reboot separately during the agreed interruption. After SSH returns, repeat the apply: once Proxmox points `/etc/pve/local` at the desired name, the script archives the empty old-node directory into the root-only backup. This opaque move preserves certificates without exposing their contents. New-node certificates and configuration are created by Proxmox during startup. Subsequent applies report no changes and require no reboot. Historical old-name metrics are retained; they are not migrated.

Finally run `host-preflight` and verify node identity, storage availability, SSH, and the web interface. If startup fails, use the physical console and preserved backups; do not disable host-key verification. This is not a general cluster or populated-node migration.

Reference: [Proxmox staff guidance on renaming](https://forum.proxmox.com/threads/changing-hostname-and-ip-of-non-empty-pve-host.112068/).

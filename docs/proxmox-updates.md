# Proxmox repositories and updates

This module prepares a standalone, empty Proxmox VE 9 node for subscription-free updates. The consumer supplies its inventory and SSH identity path. No keys or tokens are read by the framework.

## Commands

```sh
make host-repositories-plan INVENTORY=/path/to/host.toml
make host-repositories INVENTORY=/path/to/host.toml
make host-updates-plan INVENTORY=/path/to/host.toml
make host-updates INVENTORY=/path/to/host.toml
```

Repository operations use the same Proxmox API exposed in the web panel, through local `pvesh` over trusted SSH. They disable Enterprise and test entries, enable `no-subscription`, and enable the subscription-free repository matching the installed Ceph client major version. Debian base, security, and firmware repositories remain available. “Subscription-free” describes access, not the license of every Debian firmware package. There is no major Ceph migration. Parser errors, unknown active sources, authenticated URLs, unexpected suites, or a Ceph major mismatch stop the operation. Every mutation uses the current Proxmox digest to detect concurrent edits. Repeating an applied repository plan reports no changes.

Update planning refreshes indexes as a native Proxmox task, waits for successful completion, and simulates the complete dependency upgrade. This plan refreshes package metadata but installs nothing. Update application invokes `pveupgrade`, the wrapper used by Proxmox for `apt-get dist-upgrade`, equivalent to the documented full-upgrade workflow. It does not use plain `apt upgrade`.

The bootstrap path refuses clusters, guests, broken or held packages, removals, and Proxmox major upgrades. Noninteractive package configuration preserves existing configuration files. A temporary root-only APT configuration makes index errors fatal and prevents package removal. No permanent automatic-upgrade policy is installed or changed. Package updates are time-dependent: the command converges on the packages currently available in the configured repositories; it does not pin a frozen OS image.

Package output stays in `/var/log/milkyway-updates.log` with mode 0600 on the host. The script independently verifies dpkg consistency and that no simulated or native Proxmox updates remain, because the Proxmox wrapper can return zero after an underlying failure. Failures stop the operation; they never invoke `dpkg --force` or skip repository signatures. Inspect native tasks and logs locally without publishing secrets.

Reboot is separate and never automatic. Check kernel changes as well as `reboot_required`, because the distribution marker alone may not cover every Proxmox kernel update. After an agreed reboot, verify SSH, Proxmox services, storage, and the read-only preflight. Rollback of installed packages is not automatic; use console recovery if package installation fails. This module is not a maintenance procedure for an active cluster.

References: [Proxmox repositories](https://github.com/proxmox/pve-docs/blob/master/pve-package-repos.adoc), [official update procedure](https://github.com/proxmox/pve-docs/blob/master/system-software-updates.adoc), and [pveupgrade implementation](https://github.com/proxmox/pve-manager/blob/master/bin/pveupgrade).

The native CLI streams task progress before its final JSON task identifier. The adapter consumes only that final identifier and verifies the native task status. It does not pass the CLI formatter’s `--quiet` option, which suppresses the identifier. Progress output is captured and never forwarded to the caller.

The upgrade window is four hours, with a small additional SSH collection margin. SSH keepalives detect broken connections during slow downloads. On a slow link, the former one-hour window could expire during package installation; a download-only interruption preserves the APT cache and must happen before dpkg starts. Do not interrupt an active package installation to change this window.

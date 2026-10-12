# Proxmox laptop lid behavior

This optional bootstrap module keeps a laptop host running when its lid closes, on battery, external power, or a dock. The consumer chooses whether to run it; desktop hosts do not need it. An ACPI lid switch, root access, the expected host identity, and an empty standalone Proxmox VE 9 node are required.

```sh
make host-lid-plan INVENTORY=/path/to/host.toml
make host-lid INVENTORY=/path/to/host.toml
```

The script uses the inventory and trusted SSH transport shared with preflight. Planning performs no writes. Application atomically creates `/etc/systemd/logind.conf.d/90-milkyway-lid.conf`, owned by root with mode 0644, setting `HandleLidSwitch`, `HandleLidSwitchExternalPower`, and `HandleLidSwitchDocked` to `ignore`. Existing non-ignored lid policies outside that file stop the operation for review. A symlink at the managed destination is refused. Repeat application without drift preserves the file and reports `changed=false`.

Activation is an explicit reboot. The module does not restart logind during a package upgrade or reboot the host itself. Its reboot indicator compares the managed file's modification time with the current boot; after reboot, repeat the operation and check the effective configuration. Then physically close the lid while monitoring SSH and reopen it if connectivity fails. Configuration checks alone do not prove physical behavior.

Only lid-close behavior changes. Explicit suspend commands, low-battery behavior, thermal limits, and power-loss recovery retain their existing policy. Keep ventilation clear when operating with the lid closed. Rollback removes the managed drop-in followed by a separate reboot, restoring the remaining logind policy.

Reference: [systemd logind configuration](https://github.com/systemd/systemd/blob/main/man/logind.conf.xml).

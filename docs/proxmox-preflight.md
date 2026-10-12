# Proxmox installation preflight

Status: read-only installation collector implemented and exercised on physical hardware. It is an onboarding gate for an empty standalone node, not an operational health check for a host already running guests. Baseline configuration is a separate module; see [bootstrap access](bootstrap-access.md).

## Purpose and boundary

Collect installation facts before planning host changes. This first module does not install packages, join a cluster, edit storage, change network/firewall rules, enroll Tailscale, or reboot. It is deliberately independent of Authentik and OpenBao.

The consumer owns node names, addresses, and access. MilkyWay has no Mercury, domain, or private-network defaults. It reuses Jarvis's separation of inventory and host facts while keeping this first collector independent of its deployment machinery.

## Inputs and execution

Copy `examples/host.toml` to a private consumer inventory and replace its example values. The four fields under `[host]` are address, username, ssh_port, and expected_hostname. Do not add credentials. The username must currently be root because the read-only `pvesh` API interface requires root.

```sh
make host-preflight INVENTORY=/absolute/path/to/host.toml
```

Use existing SSH key authentication through the local SSH agent or normal SSH configuration. The operator must verify the host-key fingerprint against the physical console before establishing trust. The collector refuses unknown/changed host keys, interactive password prompts, and agent/port forwarding. It never automatically accepts keys or reads credential values.

Execution sends the committed collector over SSH stdin and runs it with the host's Python; no file is installed on the host. Proxmox VE 9.x supplies the expected Python and platform tools. Network access to the intended management address and a trusted SSH session must already work.

## Output and repeated runs

The report defaults to `.milkyway/preflight.json`, ignored by Git, written with mode 0600. It contains node identity, CPU count, memory, kernel/PVE versions, disk/mount metadata, interface addresses, routes, workload metadata, time synchronization, cluster membership, and the OS reboot-required marker. The marker is advisory; it does not prove a new kernel is already running or that no reboot is needed.

No arbitrary configuration, SSH key, password, token, or command failure output is collected. Reports still contain private inventory; do not publish or paste them indiscriminately. Repeating the command overwrites only the local report and repeats read-only probes. It makes no host configuration changes.

Exit status 1 means a probe failed, identity/version differed, cluster membership was found, or existing VMs/containers need a preservation plan. An empty blocker list permits baseline planning only. DNS, outbound connectivity, recovery after reboot, and authorized Tailscale reachability still need their own operational checks.

## Verification and recovery

`make check` includes offline tests for rejected SSH input, identity/version/workload guards, safe failure output, and private repeatable report writes. Physical-host onboarding has also been exercised by a consumer; environment-specific evidence belongs in that consumer repository.

On connection failure, verify the management network, trusted host fingerprint, SSH key access, and root authorization. Do not disable host-key verification to make the check pass. A report failure requires no host rollback: nothing was changed remotely. Inspect the local report and establish the installation handoff before implementing or running baseline apply.

[Proxmox pvesh documentation](https://pve.proxmox.com/pve-docs/pvesh.1.html) describes the local API interface and its root requirement.

Set `MILKYWAY_SSH_IDENTITY_FILE` to an existing local key path to select that identity with `IdentitiesOnly=yes`. The framework never reads the key contents. Otherwise SSH uses its normal configuration and agent.

# Proxmox guest startup ordering

`ansible/roles/proxmox_guest_startup` reconciles startup order through the
consumer's verified root SSH connection. Proxmox requires `Sys.Modify` on `/`
for this field, so the restricted OpenTofu API identity does not manage it.
The OpenTofu guest module ignores externally managed `startup` changes.

## Consumer contract

Call `ansible/playbooks/guest-startup.yml` after applying the VM plan and before
connecting to guests. Supply the existing `proxmox` inventory and these variables:

```yaml
proxmox_node: mercury
proxmox_pool: nimbus
proxmox_guest_startup:
  - vm_id: 101
    order: 1
  - vm_id: 102
    order: 2
  - vm_id: 103
    order: 3
```

Names and IDs above are consumer examples. The framework fixes the boot delay
at 30 seconds and shutdown delay at 60 seconds. These delays sequence boot
attempts; they do not establish service readiness.

Before writing anything, the role verifies the connected hostname, all inputs,
all guest locations and membership in the declared pool. It rejects containers,
missing guests, duplicate IDs and templates. It reads configurations without
logging their contents and runs `qm set --startup` only when values differ.
An unchanged repeat run performs no writes; check mode previews changes.
The role never starts, stops, clones or deletes a VM.

## Verification

Synthetic tests execute the actual role tasks against disposable command
fixtures. They cover reconciliation, unchanged reruns and refusal of wrong
nodes, pools, templates and duplicate IDs. Run them with the infrastructure
tool environment:

```sh
uv run --frozen --project tools/infrastructure python -m unittest discover \
  -s ansible/roles/proxmox_guest_startup/tests -p 'test_*.py'
```

These checks do not replace a live deployment and repeated-plan check.

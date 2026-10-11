# First-stage execution plan

Status: repository foundation implemented with Nebula v0.1.3. Repository checks and documentation builds are available; hosted Read the Docs publication awaits account linking. Read-only installation preflight is implemented and tested offline. Mercury baseline and its operational validation remain gated by the installation handoff. No services have been deployed.

## Objective

Establish a reproducible repository foundation, adopt it in MilkyWay and Nimbus, and then automate the minimum usable configuration of Mercury. Keep infrastructure definitions reusable and the personal environment separate.

## Delivery sequence

| Order | Deliverable | Location | Completion evidence |
| --- | --- | --- | --- |
| 1 | Repository template and development safeguards | CafofoLabs/nebula, public | A generated project installs hooks idempotently and rejects synthetic secrets, invalid commit/PR titles, and conflict markers. |
| 2 | Reconciled GitHub settings and CI | Nebula; adopted by consumers | Applied settings match the declared policy; real checks appear and become required after a successful run. |
| 3 | Changelog, optional releases, versioned docs | Nebula | Merged PRs produce traceable entries; a release creates one immutable tag and matching notes; repeating it produces no duplicate. Documentation builds from the same tag. |
| 4 | Template lifecycle and adoption | MilkyWay and Nimbus | Upgrade between two template versions preserves consumer customizations or reports conflicts. Both consumers pin an accepted template release. |
| 5 | Proxmox baseline module | MilkyWay | Read-only preflight, reviewable plan, controlled apply, post-check, and a second run without configuration drift. |
| 6 | First environment integration | TheAldersonProject/nimbus | Inventory selects Mercury and invokes the pinned MilkyWay baseline; the host is usable after an agreed reboot and retains recovery access. |

Deliver each slice in a small Conventional Commit PR. Nebula's name and public visibility are approved. Nimbus starts with documentation only; it must not pretend to have been generated from a template that does not exist yet.

## 1. Repository foundation

Create Nebula with Python tooling managed by uv and a small discoverable Makefile. Use Copier as the template mechanism. Keep application-language-specific builds outside the common core.

Reuse Jarvis's useful conventions and tooling after inspecting the actual files. Keep its environment-specific names, credentials, deployment defaults, and automatic direct-main version commits out of the template.

Provide idempotent setup and GitHub configuration reconciliation. All project documentation except README belongs under docs. Hooks and CI enforce the same conventions; outgoing-commit scanning complements staged-file scanning.

Acceptance: run setup twice in a disposable consumer, check that it has no unintended changes, and prove failure paths with synthetic fixtures outside published history.

## 2. GitHub policy and CI

Start with the policy already applied to MilkyWay. Treat it as existing remote state to reconcile, not a reason to replace stronger rules. Refuse silent weakening of protections.

Run checks without infrastructure credentials on hosted GitHub runners. Introduce required check names only after the jobs exist and have run successfully. Retain a solo-maintainer workflow: PRs required, external reviewer optional.

Verify plan support per repository. Public Nebula/MilkyWay and private personal Nimbus can have different feature availability. Explicitly report any unsupported enforcement.

## 3. Release and documentation

Use merged PR titles, preserved as squash subjects, as the changelog source. Prefer adapting established parsing/release tooling over building a custom release engine.

Prepare changelog/version edits through a release PR. An explicit release action publishes a tag and notes for the validated commit. Serialize publication and make retries safe. Test automation-triggered checks before depending on them; do not solve event restrictions by bypassing main protection.

Use Sphinx/MyST and Read the Docs Community for Nebula and MilkyWay. Build documentation in CI before publication. A failed hosted docs build is an incomplete documentation publication, not evidence that deployment succeeded.

Nimbus keeps its documentation private by default; local documentation builds are enough for this stage. Public documentation must never import Nimbus inventory or private environment values.

Acceptance: rehearse two changes, one release, a retry, and a template upgrade in a disposable project. Verify the remote tag and the hosted documentation version, not only local command success.

## 4. Adoption

Tag the validated Nebula foundation, adopt that version in MilkyWay and Nimbus, and record Copier's non-secret answers. Preserve MilkyWay's branding and plans and Nimbus's private documentation.

Separate ownership:

- Nebula: repository lifecycle and development tools.
- MilkyWay: infrastructure behavior, module interfaces, and generic examples.
- Nimbus: selected versions, hosts, networks, domains, and service placement.

Template and framework versions advance independently. Consumer updates are reviewable PRs, never silent replacements.

## 5. Mercury baseline after installation

The operator installs Proxmox. Before changing the host, collect a read-only inventory: installed version, hostname, CPU/RAM, disk layout, bridge/interface names, address/gateway/DNS, connectivity, and existing workloads. Do not assume hardware details from earlier Geri or Yoga discussions.

Define the first module narrowly: supported repositories and updates, clock/DNS, management access, host firewall, and Tailscale onboarding. It must expose check/plan/apply/verify behavior through the Makefile and document inputs, privileges, idempotence, and recovery.

Bootstrap uses a temporary explicitly allowed management path. Enroll and verify authorized Tailscale access before removing temporary LAN access or tightening rules that could lock out the operator. Initial authorization and credentials must use a secure local channel; never paste them into chat or Git. Keep physical-console recovery possible.

Do not require Authentik or OpenBao for the bootstrap of the host that will eventually run them. Reboots are reported and deliberately scheduled, never hidden inside a generic setup command.

Acceptance: management remains available through the intended private path, required outbound access works, unexpected inbound access is blocked, and a second apply has no pending configuration changes. Validate reboot recovery with the operator when appropriate.

## Operator handoff: Mercury

1. Install Proxmox on the intended disk, using the node name mercury and the agreed hostname mercury.cafofolabs.cloud.
2. Use wired connectivity to the ER605. Confirm the reserved/static address is not duplicated or leased to another host.
3. Confirm web management access from the installation network, outbound Internet access, DNS, and time synchronization.
4. Reboot once and verify management access returns.
5. Report completion and non-secret facts: Proxmox version, management address, installation disk/storage layout, and whether reboot succeeded.

Do not share passwords or tokens. The automatic baseline starts only after this handoff and its access method are ready. Do not join an existing cluster or deploy the service stack during this manual installation stage.

## Later stages

After the baseline, plan the portable VM/container layout and deploy Authentik, OpenBao, private DNS/TLS ingress, Komodo, and observability in dependency order. Cluster expansion, backup policy, application provisioning, and the public SDK remain separate increments. No service rollout is included in the repository-foundation milestone.

## Human decisions and actions

- Already settled: Nebula and MilkyWay public; Nimbus as the homelab consumer; Mercury as the first host; Tailscale retained.
- Operator actions: physical installation, read-only handoff facts, secure initial-access authorization, and the initial Read the Docs connection if interactive consent is needed.
- Ask only if a paid account feature, a visibility change, destructive storage action, or a recovery-affecting choice becomes necessary.

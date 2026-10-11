# Foundation plan

Status: proposed; repository automation and infrastructure changes are not implemented by this document.

## Ownership

| Project | Responsibility |
| --- | --- |
| CafofoLabs/Nebula | Language-independent repository safeguards, tooling, documentation, releases, and template upgrades. |
| CafofoLabs/MilkyWay | Versioned infrastructure modules and interfaces for provisioning and configuring shared services. |
| TheAldersonProject/Nimbus | Inventory, host names, networks, domains, placement, and environment-specific configuration. |

The template must work without MilkyWay. MilkyWay must work without this particular homelab. Mercury is the first homelab Proxmox host, not a framework default. Application projects own their deployments and consume infrastructure through explicit interfaces.

## 1. Build the reusable repository foundation

Use Copier for both project creation and controlled updates from tagged template versions. Keep the template version and non-secret answers in `.copier-answers.yml`.

Updates run on a `chore/template-update-*` branch, produce a reviewable PR, and pass the project's own checks. Conflicts require resolution; updates must not silently replace consumer customizations. Never use destructive recopy as the normal upgrade mechanism. Test an update between two template releases after a consumer has made local changes.

Keep the first template small. Support projects regardless of their implementation language. Offer extension points for their own build and test commands instead of generating unnecessary language stacks. Template and consumer releases are independent.

## 2. Protect repositories and local development

- Require PRs and successful, uniquely named CI checks before merging into `main`.
- Block force pushes and deletion of protected branches. Apply protections to administrators where supported; do not depend on routine bypasses.
- Use squash merges and preserve the validated Conventional Commit PR title as the commit subject, including the PR reference.
- Validate branch prefixes such as `feature/`, `fix/`, `chore/`, and `docs/`; reject `codex` branch names.
- Validate Conventional Commits locally and in CI, including PR titles.
- Install secret scanning in pre-commit and inspect outgoing commits before push; repeat scanning in CI. CI alone cannot prevent the initial upload of a secret.
- Exclude local credentials, state, generated environments, and private inventory through appropriate ignore rules. Never store credential values in template answers.
- Verify project-local personal Git identity and never add AI co-author trailers.
- Use minimal workflow permissions and pinned tool/action versions. PR checks require no homelab credentials.
- Reject unresolved merge-conflict markers and files.

A solo maintainer should not be locked out by a mandatory second-person approval they cannot provide. Require PRs and checks initially; make human-review requirements configurable.

Repository settings must have an idempotent plan/apply interface with post-apply verification. A plan limitation is an explicit unmet requirement, never a successful protection result.

## 3. Add a small Python tooling layer

Use `pyproject.toml`, `uv.lock`, and a small tooling directory for validation, configuration reconciliation, and orchestration. Python is a development tool dependency, not a requirement for the application's implementation language.

Reuse Jarvis patterns selectively: discoverable Makefile help, locked dependencies, isolated checks, and its conventional-history/changelog approach. Evaluate reuse of git-cliff rather than writing a new commit parser or release engine. Do not copy its environment defaults or direct pushes to `main`.

Proposed Makefile interface:

| Target | Purpose |
| --- | --- |
| `make help` | List supported commands. |
| `make setup` | Converge local dependencies and hooks safely on repeated runs. |
| `make check` | Run repository safeguards and configured project checks. |
| `make test` | Run meaningful tooling and template lifecycle tests. |
| `make repo-plan` / `make repo-apply` | Inspect and reconcile supported GitHub settings. |
| `make docs` | Build documentation locally. |
| `make release-plan` | Preview version and changelog without publishing. |
| `make release` | Request the protected release workflow. |
| `make template-update` | Prepare an update from a selected template release. |

These are proposed interfaces, not commands available in this repository today.

## 4. Maintain changelog and publish optional releases

The source of truth is accepted history: **merged PRs**, not merely opened PRs. Validate titles before merge and snapshot them in squash commit subjects so later PR-title edits cannot silently rewrite release history.

Generate `docs/CHANGELOG.md` from that history, grouped by release and change type, with PR links. This location preserves the rule that only README Markdown lives at the root. Preserve existing released entries and support rebuilding history without duplicate entries.

Proposed flow:

1. A normal PR passes checks and merges by squash.
2. Automation creates or refreshes one maintenance/release PR with the changelog's unreleased entries.
3. An explicit release request calculates the SemVer version and prepares the versioned entry in that PR. Release notes exclude maintenance-only bookkeeping commits.
4. The release PR passes the same protections and merges.
5. The release job tags the exact validated release commit as `vX.Y.Z` and publishes matching GitHub release notes.
6. Read the Docs builds that same tag. Report documentation publication independently until its build succeeds.

Feature, fix, and breaking-change titles drive version planning. Documentation-only changes can remain unreleased or use an explicit patch release. Do not emit a version merely because a PR was opened.

Use concurrency control and verify the release baseline before publishing. Repeated runs must not duplicate notes, releases, or tags. Existing tags must never be moved. Recovery should resume only missing steps, including failed documentation builds.

Do not let a release bot bypass protected `main`. Select the supported GitHub automation identity/event chain during implementation so automation-created PRs still receive required checks.

## 5. Publish versioned documentation

Use Sphinx with MyST for Markdown documentation, a Read the Docs theme, and `.readthedocs.yaml`. All documentation Markdown remains under `docs/`, apart from the short root README.

Validate documentation in PR CI. Configure Read the Docs to build released tags and maintain stable/latest views deliberately. The release must not be reported as fully documented until the corresponding documentation build succeeds.

Every module documents its purpose, inputs, outputs, permissions, execution path, repeated-run behavior, verification, and recovery. Keep one canonical source for commands rather than duplicating instructions across the README and module docs.

The initial Read the Docs account/repository integration and any required authorization must be established explicitly. No credentials belong in generated files. Version activation should use documented automation rules.

## 6. Prove the template before adopting it

Acceptance requires a disposable generated project that demonstrates:

- repeated setup leaves hooks and configuration consistent;
- synthetic secret fixtures and invalid commit/PR titles are rejected;
- branch protection is actually enforced on GitHub;
- a template upgrade preserves consumer changes or reports conflicts;
- two merged PRs produce the expected changelog and one release;
- rerunning release creates no duplicates and does not move tags;
- documentation for the release tag builds successfully.

Use synthetic secret fixtures outside real project history. Do not publish real credentials to test scanning.

Then adopt the first tagged template release in MilkyWay. Implement the first infrastructure module only after repository safeguards and documentation/release behavior are established.

## Confirmed decisions and remaining setup

- Nebula is the public, language-independent project template under CafofoLabs.
- MilkyWay and its documentation are public. Use Read the Docs Community; its account/repository integration still needs to be established.
- Nimbus is the homelab consumer under TheAldersonProject. It starts private; do not publish its inventory or documentation through the public framework documentation.
- MilkyWay main protection is configured: PR required, administrator enforcement, no force pushes or deletion, linear history, resolved conversations, and squash-only merging. Required CI checks are pending implementation.
- Nimbus private-repository protection must be verified independently against the personal account's capabilities. Never change visibility or purchase a plan implicitly.
- See the [first-stage execution plan](execution-plan.md) for sequencing and acceptance gates.

## Sources

- [Copier updates and conflict handling](https://copier.readthedocs.io/en/stable/updating/)
- [GitHub protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [Read the Docs version automation](https://docs.readthedocs.com/platform/stable/automation-rules.html)
- [Read the Docs private repositories](https://docs.readthedocs.com/platform/stable/commercial/index.html)

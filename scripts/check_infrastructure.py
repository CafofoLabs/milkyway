"""Validate infrastructure in isolated directories without live credentials."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools" / "infrastructure"
TOFU_VERSION = "1.12.6"


def run(arguments: list[str], *, cwd: Path, environment: dict[str, str]) -> str:
    result = subprocess.run(
        arguments,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"{' '.join(arguments)} failed in {cwd.name}:\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result.stdout


def isolated_environment(directory: Path) -> dict[str, str]:
    # Do not inherit provider credentials, CLI tokens, inventories or debug logs.
    environment = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")
        if key in os.environ
    }
    home = directory / "home"
    home.mkdir()
    config = directory / "tofu.rc"
    config.write_text("")
    environment.update(
        {
            "HOME": str(home),
            "TMPDIR": str(directory),
            "TF_IN_AUTOMATION": "1",
            "TF_INPUT": "0",
            "TF_CLI_CONFIG_FILE": str(config),
            "ANSIBLE_CONFIG": str(ROOT / "ansible" / "ansible.cfg"),
            "ANSIBLE_FILTER_PLUGINS": str(ROOT / "ansible/filter_plugins"),
            "ANSIBLE_LOCAL_TEMP": str(directory / "ansible-local"),
            "ANSIBLE_REMOTE_TEMP": str(directory / "ansible-remote"),
            "ANSIBLE_PYTHON_INTERPRETER": sys.executable,
            "ANSIBLE_COLLECTIONS_SCAN_SYS_PATH": "false",
            "ANSIBLE_NOCOLOR": "1",
        }
    )
    return environment


def tofu_checks(directory: Path, environment: dict[str, str]) -> None:
    version = json.loads(
        run(["tofu", "version", "-json"], cwd=ROOT, environment=environment)
    )
    if version["terraform_version"] != TOFU_VERSION:
        raise RuntimeError(f"OpenTofu {TOFU_VERSION} is required.")
    run(
        ["tofu", "fmt", "-check", "-recursive", "tofu", str(TOOLS / "fixtures")],
        cwd=ROOT,
        environment=environment,
    )
    cache = TOOLS / ".venv" / "tofu-plugin-cache"
    cache.mkdir(parents=True, exist_ok=True)
    environment["TF_PLUGIN_CACHE_DIR"] = str(cache)
    for source in sorted((ROOT / "tofu" / "modules").iterdir()):
        if not source.is_dir() or not list(source.glob("*.tf")):
            continue
        module = directory / "modules" / source.name
        shutil.copytree(
            source,
            module,
            ignore=shutil.ignore_patterns(
                ".terraform",
                "*.tfstate*",
                "*.tfplan",
                "*.tfvars*",
                ".env*",
                "*.key",
                "*.pem",
                "crash.log",
            ),
        )
        fixture = TOOLS / "fixtures" / source.name / "contract.tftest.hcl"
        if fixture.exists():
            (module / "tests").mkdir(exist_ok=True)
            shutil.copyfile(fixture, module / "tests" / "contract.tftest.hcl")
        if not list((module / "tests").glob("*.tftest.hcl")):
            raise RuntimeError(f"Mocked contract tests are required for {source.name}.")
        print(f"Checking OpenTofu module {source.name}...", flush=True)
        run(
            ["tofu", "init", "-backend=false", "-input=false", "-no-color"],
            cwd=module,
            environment=environment,
        )
        run(["tofu", "validate", "-no-color"], cwd=module, environment=environment)
        run(["tofu", "test", "-no-color"], cwd=module, environment=environment)
        print(
            f"  {source.name}: initialized, validated, mocked tests passed", flush=True
        )


def ansible_checks(directory: Path, environment: dict[str, str]) -> None:
    for source in sorted((ROOT / "ansible").rglob("*.yml")):
        yaml.safe_load(source.read_text())
    yaml.safe_load((TOOLS / "collections.yml").read_text())
    collections = TOOLS / ".venv" / "collections"
    environment["ANSIBLE_COLLECTIONS_PATH"] = str(collections)
    run(
        [
            "ansible-galaxy",
            "collection",
            "install",
            "--no-deps",
            "--requirements-file",
            str(TOOLS / "collections.yml"),
            "--collections-path",
            str(collections),
        ],
        cwd=ROOT,
        environment=environment,
    )
    hosts = {
        "check-proxmox": {"ansible_host": "192.0.2.10"},
        "check-identity": {"ansible_host": "192.0.2.20"},
        "check-vault": {"ansible_host": "192.0.2.21"},
        "check-platform": {"ansible_host": "192.0.2.22"},
    }
    groups = {
        "proxmox": ["check-proxmox"],
        "platform_vms": ["check-identity", "check-vault", "check-platform"],
        "authentik": ["check-identity"],
        "openbao": ["check-vault"],
        "traefik": ["check-identity", "check-vault", "check-platform"],
        "observability": ["check-platform"],
        "komodo": ["check-platform"],
    }
    inventory = {
        "all": {
            "vars": {
                "env_name": "infrastructure-check",
                "platform_access_mode": "bootstrap",
                "platform_secret_files_dir": str(directory / "synthetic-secrets"),
                "milkyway_secrets_dir": str(directory / "synthetic-secrets"),
                "milkyway_tofu_workdir": str(directory / "synthetic-foundation"),
                "platform_initial_management_cidr": "192.0.2.100/32",
                "platform_ssh_identity_file": str(directory / "not-a-private-key"),
            },
            "hosts": hosts,
            "children": {
                name: {"hosts": {member: {} for member in members}}
                for name, members in groups.items()
            },
        }
    }
    inventory_file = directory / "inventory.json"
    inventory_file.write_text(json.dumps(inventory))
    playbooks = sorted((ROOT / "ansible" / "playbooks").glob("*.yml"))
    for playbook in playbooks:
        run(
            [
                "ansible-playbook",
                "--inventory",
                str(inventory_file),
                "--syntax-check",
                str(playbook),
            ],
            cwd=ROOT,
            environment=environment,
        )
    print(
        f"Ansible: YAML parsed, {len(playbooks)} playbooks passed synthetic syntax checks",
        flush=True,
    )
    run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "ansible/roles/openbao/tests/test_seal_guard.py",
            "ansible/roles/openbao/tests/test_restart_readiness.py",
            "ansible/roles/proxmox_tls/tests/test_tls.py",
            "ansible/roles/proxmox_guest_startup/tests/test_startup.py",
        ],
        cwd=ROOT,
        environment=environment,
    )
    print("OpenBao and Proxmox TLS: isolated runtime guard tests passed", flush=True)


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="mw-check-", dir="/tmp") as temporary:
            directory = Path(temporary)
            environment = isolated_environment(directory)
            tofu_checks(directory, environment)
            ansible_checks(directory, environment)
    except (
        RuntimeError,
        OSError,
        subprocess.TimeoutExpired,
        ValueError,
        yaml.YAMLError,
    ) as error:
        print(f"Infrastructure check failed: {error}", file=sys.stderr)
        return 1
    print("Infrastructure checks passed; no live inventory or credentials were used.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

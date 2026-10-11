import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "preflight", Path(__file__).resolve().parents[1] / "scripts/proxmox_preflight.py"
)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def host():
    return {
        "address": "192.0.2.10",
        "username": "root",
        "ssh_port": 22,
        "expected_hostname": "node-a",
    }


def facts():
    return {
        "schema_version": 1,
        "hostname": "node-a",
        "version": "pve-manager/9.2.0/hash",
        "cluster_configured": False,
        "resources": [],
        "errors": [],
    }


@pytest.mark.parametrize(
    "address", ["-oProxyCommand=bad", "node;bad", "node\nbad", "user@host"]
)
def test_rejects_ssh_argument_injection(tmp_path, address):
    path = tmp_path / "inventory.toml"
    values = {**host(), "address": address}
    path.write_text(
        "[host]\n" + "\n".join(f"{k} = {json.dumps(v)}" for k, v in values.items())
    )
    with pytest.raises(ValueError):
        preflight.host_config(path)


def test_extra_inventory_fields_are_rejected(tmp_path):
    path = tmp_path / "inventory.toml"
    path.write_text('[host]\npassword = "synthetic-placeholder"\n')
    with pytest.raises(ValueError, match="only"):
        preflight.host_config(path)


def test_preflight_blocks_mismatches_and_existing_workloads():
    assert preflight.assess(facts(), host()) == []
    observed = {
        **facts(),
        "hostname": "other",
        "version": "pve-manager/8.4/hash",
        "cluster_configured": True,
        "resources": [{"type": "qemu", "vmid": 100}],
        "errors": ["disks"],
    }
    blockers = preflight.assess(observed, host())
    assert len(blockers) == 5
    assert "disks" in blockers


def test_ssh_requires_trusted_key_and_disables_forwarding():
    args = preflight.ssh_args(host())
    assert "StrictHostKeyChecking=yes" in args
    assert "BatchMode=yes" in args
    assert "ForwardAgent=no" in args
    assert "ServerAliveInterval=30" in args
    assert "ServerAliveCountMax=3" in args
    assert args[-1] == "python3 - --collect"


def test_failed_probe_never_echoes_arbitrary_output(monkeypatch):
    def failing(*args, **kwargs):
        raise subprocess.CalledProcessError(
            1, args[0], output="unexpected-private-output"
        )

    monkeypatch.setattr(
        preflight.Path, "read_text", lambda self: "MemTotal: 8192000 kB\n"
    )
    monkeypatch.setattr(preflight.subprocess, "run", failing)
    result = preflight.collect()
    assert result["errors"] == list(preflight.COMMANDS)
    assert "unexpected-private-output" not in json.dumps(result)


def test_report_is_private_repeatable_and_does_not_follow_symlinks(tmp_path):
    path = tmp_path / "preflight.json"
    preflight.save_report(path, facts())
    first = path.read_bytes()
    path.chmod(0o644)
    preflight.save_report(path, facts())
    assert path.read_bytes() == first
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    link = tmp_path / "link.json"
    os.symlink(path, link)
    with pytest.raises(OSError):
        preflight.save_report(link, {})
    assert path.read_bytes() == first


def test_explicit_identity_is_used_without_reading_it(tmp_path, monkeypatch):
    identity = tmp_path / "identity"
    identity.touch()
    monkeypatch.setenv("MILKYWAY_SSH_IDENTITY_FILE", str(identity))
    monkeypatch.setattr(
        preflight.Path,
        "read_text",
        lambda self: pytest.fail("Identity contents must not be read"),
    )
    args = preflight.ssh_args(host())
    assert args[args.index("-i") + 1] == str(identity)
    assert "IdentitiesOnly=yes" in args

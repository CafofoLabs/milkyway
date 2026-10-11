import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "hostname", Path(__file__).resolve().parents[1] / "scripts/proxmox_hostname.py"
)
hostname = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hostname)


def test_hosts_preserves_other_entries_and_is_repeatable():
    before = "127.0.0.1 localhost\n192.0.2.10 old.example.org old # management\n::1 localhost\n"
    after = hostname.rewrite_hosts(before, "old", "node-a", "192.0.2.10")
    assert after == before.replace("old.example.org old", "node-a.example.org node-a")
    assert hostname.rewrite_hosts(after, "old", "node-a", "192.0.2.10") == after


@pytest.mark.parametrize(
    "text",
    [
        "127.0.0.1 localhost\n",
        "192.0.2.10 unrelated\n",
        "192.0.2.10 old\n192.0.2.10 old\n",
    ],
)
def test_hosts_refuses_ambiguous_or_unexpected_identity(text):
    with pytest.raises(ValueError):
        hostname.rewrite_hosts(text, "old", "node-a", "192.0.2.10")


def test_old_node_with_guest_or_unknown_configuration_is_preserved(tmp_path):
    guests = tmp_path / "qemu-server"
    guests.mkdir()
    hostname.validate_node(tmp_path)
    guest = guests / "100.conf"
    guest.write_text("synthetic guest")
    with pytest.raises(ValueError):
        hostname.validate_node(tmp_path)
    guest.unlink()
    (tmp_path / "unexpected.conf").touch()
    with pytest.raises(ValueError):
        hostname.validate_node(tmp_path)


@pytest.mark.parametrize("blocker", ["cluster", "guest"])
def test_remote_refuses_cluster_and_workloads_before_writes(monkeypatch, blocker):
    monkeypatch.setattr(hostname.os, "geteuid", lambda: 0)
    monkeypatch.setattr(hostname.Path, "exists", lambda self: blocker == "cluster")
    monkeypatch.setattr(
        hostname.Path, "write_text", lambda *args: pytest.fail("Must not write")
    )
    monkeypatch.setattr(
        hostname,
        "command",
        lambda *args: (
            "pve-manager/9.2.2/hash" if args[0] == "pveversion" else '[{"type":"qemu"}]'
        ),
    )
    with pytest.raises(ValueError):
        hostname.remote("apply", "old", "new", "192.0.2.10")

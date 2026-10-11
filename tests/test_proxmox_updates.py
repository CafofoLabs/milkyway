import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "updates", Path(__file__).resolve().parents[1] / "scripts/proxmox_updates.py"
)
updates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updates)


def repositories():
    return {
        "files": [
            {
                "path": "/etc/apt/sources.list.d/pve.sources",
                "repositories": [
                    {
                        "Enabled": True,
                        "URIs": ["https://enterprise.proxmox.com/debian/pve"],
                        "Suites": ["trixie"],
                        "Components": ["pve-enterprise"],
                    }
                ],
            }
        ],
        "errors": [],
        "standard-repos": [
            {"handle": "no-subscription"},
            {"handle": "ceph-squid-no-subscription"},
        ],
    }


def test_repository_plan_converges():
    data = repositories()
    assert updates.repository_plan(data, "ceph-squid-no-subscription") == {
        "disable": [{"path": "/etc/apt/sources.list.d/pve.sources", "index": 0}],
        "add": ["no-subscription", "ceph-squid-no-subscription"],
    }
    data["files"][0]["repositories"][0]["Enabled"] = False
    for repo in data["standard-repos"]:
        repo["status"] = True
    assert updates.repository_plan(data, "ceph-squid-no-subscription") == {
        "disable": [],
        "add": [],
    }


@pytest.mark.parametrize(
    "uri",
    [
        "https://unexpected.invalid/debian",
        "https://user:synthetic@deb.debian.org/debian",
        "https://download.proxmox.com/debian/ceph-tentacle",
    ],
)
def test_repository_plan_rejects_unknown_credentials_or_major_transition(uri):
    data = repositories()
    data["files"][0]["repositories"][0]["URIs"] = [uri]
    with pytest.raises(ValueError):
        updates.repository_plan(data, "ceph-squid-no-subscription")


def test_upgrade_simulation_detects_install_and_refuses_removals_and_major_upgrade():
    assert updates.simulation(
        "Inst pve-manager [9.2.2] (9.2.3 Proxmox [amd64])\nConf pve-manager (9.2.3)"
    ) == [{"package": "pve-manager", "version": "9.2.3"}]
    assert updates.simulation("0 upgraded, 0 newly installed, 0 to remove") == []
    for text in [
        "Remv proxmox-ve [9.2]",
        "Inst pve-manager [9.2.2] (10.0 Proxmox [amd64])",
        "Inst broken-format",
    ]:
        with pytest.raises(ValueError):
            updates.simulation(text)


def test_failed_native_refresh_blocks_upgrade(monkeypatch):
    answers = iter(["UPID:synthetic", {"status": "stopped", "exitstatus": "ERROR"}])
    monkeypatch.setattr(updates, "api", lambda *a, **k: next(answers))
    with pytest.raises(ValueError, match="refresh failed"):
        updates.refresh("node-a", {})


def test_native_refresh_progress_is_not_parsed_as_json(monkeypatch):
    task = "UPID:node-a:00000001:00000002:00000003:aptupdate::root@pam:"
    monkeypatch.setattr(
        updates,
        "run",
        lambda *a, **k: (
            "starting apt-get update\nReading package lists...\n"
            + __import__("json").dumps(task)
        ),
    )
    assert updates.api("node-a", "create", "apt/update") == task


def test_refresh_does_not_hide_task_id_with_formatter_quiet(monkeypatch):
    calls = []

    def api(*args, **kwargs):
        calls.append(args)
        return (
            "UPID:node-a:synthetic"
            if args[1] == "create"
            else {"status": "stopped", "exitstatus": "OK"}
        )

    monkeypatch.setattr(updates, "api", api)
    updates.refresh("node-a", {})
    assert "--quiet" not in calls[0]

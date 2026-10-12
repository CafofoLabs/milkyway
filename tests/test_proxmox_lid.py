import importlib.util
import os
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "lid", Path(__file__).resolve().parents[1] / "scripts/proxmox_lid.py"
)
lid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lid)


def test_plan_does_not_write_and_repeated_apply_preserves_file(tmp_path, monkeypatch):
    destination = tmp_path / "drop-in" / "lid.conf"
    monkeypatch.setattr(
        lid,
        "run",
        lambda *args: "# /etc/systemd/logind.conf\n[Login]\n#HandleLidSwitch=suspend",
    )
    monkeypatch.setattr(lid.os, "fchown", lambda *args: None)
    original_stat = Path.stat

    def root_metadata(path, *args, **kwargs):
        metadata = original_stat(path, *args, **kwargs)
        if path == destination:
            values = list(metadata)
            values[4:6] = [0, 0]
            return os.stat_result(values)
        return metadata

    monkeypatch.setattr(Path, "stat", root_metadata)
    assert lid.configure("plan", destination)["changed"]
    assert not destination.exists()
    assert lid.configure("apply", destination)["changed"]
    before = destination.stat().st_mtime
    assert not lid.configure("apply", destination)["changed"]
    assert destination.stat().st_mtime == before


def test_conflicting_external_policy_stops_before_write(tmp_path, monkeypatch):
    destination = tmp_path / "lid.conf"
    monkeypatch.setattr(
        lid,
        "run",
        lambda *args: (
            "# /etc/systemd/logind.conf.d/custom.conf\n[Login]\nHandleLidSwitch=suspend"
        ),
    )
    with pytest.raises(ValueError):
        lid.configure("apply", destination)
    assert not destination.exists()


def test_symlink_is_never_replaced(tmp_path):
    original = tmp_path / "original"
    original.write_text("preserve")
    destination = tmp_path / "lid.conf"
    destination.symlink_to(original)
    with pytest.raises(ValueError):
        lid.configure("apply", destination)
    assert original.read_text() == "preserve"


@pytest.mark.parametrize("blocker", ["identity", "cluster", "guest", "no-lid"])
def test_remote_guards_prevent_configuration(monkeypatch, blocker):
    monkeypatch.setattr(lid.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        lid.socket,
        "gethostname",
        lambda: "wrong" if blocker == "identity" else "node-a",
    )
    monkeypatch.setattr(Path, "exists", lambda self: blocker == "cluster")
    monkeypatch.setattr(Path, "is_dir", lambda self: False)
    monkeypatch.setattr(
        lid,
        "run",
        lambda *args: (
            "pve-manager/9.2.2/hash"
            if args[0] == "pveversion"
            else '[{"type":"qemu"}]'
            if blocker == "guest"
            else "[]"
        ),
    )
    monkeypatch.setattr(
        lid, "configure", lambda *args: pytest.fail("Must not configure")
    )
    with pytest.raises(ValueError):
        lid.remote("apply", "node-a")

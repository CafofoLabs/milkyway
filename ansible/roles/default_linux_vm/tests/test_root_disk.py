"""Exercise the root disk growth tasks against simulated block devices."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
TASKS = ROOT / "roles" / "default_linux_vm" / "tasks" / "root_disk.yml"
GIB = 1024**3
pytestmark = pytest.mark.skipif(
    not shutil.which("ansible-playbook"), reason="Ansible is required"
)

SHIM = """
import json, sys
from pathlib import Path

state_file = Path(__file__).with_name("state.json")
state = json.loads(state_file.read_text())
name, args = Path(sys.argv[0]).name, sys.argv[1:]
state["calls"].append([name, *args])
code = 0
if name == "findmnt":
    print(f"/dev/sda1 {state['fstype']}")
elif name == "lsblk" and "--bytes" in args:
    print(state["part_bytes"])
elif name == "lsblk":
    print("part sda" if state["type"] == "part" else state["type"])
elif name == "tee":
    sys.stdin.read()
elif name == "growpart":
    if state.get("growpart_error"):
        print("FAILED: simulated", file=sys.stderr)
        code = 2
    elif state["part_bytes"] < state["disk_bytes"]:
        state["part_bytes"] = state["disk_bytes"]
        print("CHANGED: partition=1 start=2048")
    else:
        print("NOCHANGE: partition 1 is size 1. it cannot be grown")
        code = 1
elif name == "dumpe2fs":
    print(f"Block count:              {state['fs_blocks']}")
    print("Block size:               4096")
elif name == "resize2fs":
    state["fs_blocks"] = state["part_bytes"] // 4096
state_file.write_text(json.dumps(state))
sys.exit(code)
"""


@pytest.fixture
def disk(tmp_path):
    tasks = yaml.safe_load(TASKS.read_text())
    tasks = [task for task in tasks if "ansible.builtin.apt" not in task]
    sysfs = tmp_path / "sys"

    def isolate(value):
        if isinstance(value, str):
            return value.replace("/sys/class/block/", f"{sysfs}/")
        if isinstance(value, list):
            return [isolate(item) for item in value]
        if isinstance(value, dict):
            return {key: isolate(item) for key, item in value.items()}
        return value

    tasks = isolate(tasks)
    (sysfs / "sda1").mkdir(parents=True)
    (sysfs / "sda1" / "partition").write_text("1\n")
    (sysfs / "sda" / "device").mkdir(parents=True)
    (sysfs / "sda" / "device" / "rescan").write_text("")
    shims = tmp_path / "bin"
    shims.mkdir()
    script = shims / "shim.py"
    script.write_text(f"#!{sys.executable}\n{SHIM}")
    script.chmod(0o755)
    for name in ("findmnt", "lsblk", "tee", "growpart", "dumpe2fs", "resize2fs"):
        (shims / name).symlink_to(script)
    state_file = shims / "state.json"
    config = tmp_path / "ansible.cfg"
    config.write_text("[defaults]\n")
    env = {key: os.environ[key] for key in ("LANG", "LC_ALL") if key in os.environ}
    env.update(
        {
            "PATH": f"{shims}{os.pathsep}{os.environ.get('PATH', '')}",
            "HOME": str(tmp_path),
            "ANSIBLE_CONFIG": str(config),
            "ANSIBLE_LOCAL_TEMP": str(tmp_path / "local"),
            "ANSIBLE_REMOTE_TEMP": str(tmp_path / "remote"),
            "ANSIBLE_NOCOLOR": "1",
            "ANSIBLE_PYTHON_INTERPRETER": sys.executable,
        }
    )
    play = tmp_path / "play.yml"
    play.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "tasks": tasks,
                }
            ],
            sort_keys=False,
        )
    )

    class Fixture:
        def seed(self, *, disk_gb, part_gb, fs_gb, fstype="ext4", kind="part"):
            state_file.write_text(
                json.dumps(
                    {
                        "fstype": fstype,
                        "type": kind,
                        "disk_bytes": disk_gb * GIB,
                        "part_bytes": part_gb * GIB,
                        "fs_blocks": fs_gb * GIB // 4096,
                        "calls": [],
                    }
                )
            )

        def state(self):
            return json.loads(state_file.read_text())

        def update(self, **values):
            state = self.state()
            state.update(values)
            state_file.write_text(json.dumps(state))

        def run(self, *, expect_success=True):
            state = self.state()
            state["calls"] = []
            state_file.write_text(json.dumps(state))
            result = subprocess.run(
                ["ansible-playbook", "-i", "localhost,", str(play)],
                capture_output=True,
                text=True,
                env=env,
                timeout=60,
                check=False,
            )
            output = result.stdout + result.stderr
            assert (result.returncode == 0) == expect_success, output
            return output

        def calls(self, name):
            return [call for call in self.state()["calls"] if call[0] == name]

    return Fixture()


def changed(output):
    return int(output.split("changed=", 1)[1].split()[0])


def test_grows_partition_and_filesystem_once(disk):
    disk.seed(disk_gb=60, part_gb=50, fs_gb=50)
    assert changed(disk.run()) == 2
    state = disk.state()
    assert state["part_bytes"] == 60 * GIB
    assert state["fs_blocks"] == 60 * GIB // 4096
    assert disk.calls("growpart") == [["growpart", "/dev/sda", "1"]]
    assert disk.calls("resize2fs") == [["resize2fs", "/dev/sda1"]]
    assert disk.calls("tee")

    assert changed(disk.run()) == 0
    assert disk.calls("resize2fs") == []


def test_unaligned_partition_tail_is_not_a_resize(disk):
    disk.seed(disk_gb=50, part_gb=50, fs_gb=50)
    disk.update(part_bytes=50 * GIB + 512, disk_bytes=50 * GIB + 512)
    assert changed(disk.run()) == 0
    assert disk.calls("resize2fs") == []


def test_filesystem_catches_up_with_a_grown_partition(disk):
    disk.seed(disk_gb=60, part_gb=60, fs_gb=50)
    assert changed(disk.run()) == 1
    assert disk.calls("resize2fs") == [["resize2fs", "/dev/sda1"]]


@pytest.mark.parametrize("fstype,kind", [("xfs", "part"), ("ext4", "lvm")])
def test_unsupported_root_layout_fails_before_changes(disk, fstype, kind):
    disk.seed(disk_gb=60, part_gb=50, fs_gb=50, fstype=fstype, kind=kind)
    output = disk.run(expect_success=False)
    assert "Root disk growth supports only ext4" in output
    assert disk.calls("growpart") == []
    assert disk.calls("resize2fs") == []


def test_growpart_failure_stops_before_filesystem_resize(disk):
    disk.seed(disk_gb=60, part_gb=50, fs_gb=50)
    disk.update(growpart_error=True)
    disk.run(expect_success=False)
    assert disk.calls("resize2fs") == []

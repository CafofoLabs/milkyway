"""Execute the real startup role against isolated Proxmox command fixtures."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


@unittest.skipUnless(shutil.which("ansible-playbook"), "Ansible is required")
class StartupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="milkyway-startup-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.fixture = {
            "locations": [{"vmid": 101, "type": "qemu", "node": "node-a"}],
            "pool": {"members": [{"vmid": 101, "type": "qemu"}]},
            "config": {"101": {}},
        }
        self.entries = [{"vm_id": 101, "order": 1}]
        binary = self.root / "bin"
        binary.mkdir()
        script = "#!" + sys.executable + "\n" + r'''
import json, os, sys
from pathlib import Path
root = Path(os.environ["STARTUP_FIXTURE_DIR"])
data = json.loads((root / "fixture.json").read_text())
args = sys.argv[1:]
if Path(sys.argv[0]).name == "pvesh":
    path = args[1]
    if path == "/cluster/resources":
        result = data["locations"]
    elif path == "/pools/test-pool":
        result = data["pool"]
    else:
        result = data["config"][path.split("/")[-2]]
    print(json.dumps(result))
elif args[0] == "set" and args[2] == "--startup":
    with (root / "writes.jsonl").open("a") as stream:
        stream.write(json.dumps(args) + "\n")
    data["config"][args[1]]["startup"] = args[3]
    (root / "fixture.json").write_text(json.dumps(data))
else:
    sys.exit("Unexpected fixture command")
'''
        for name in ("pvesh", "qm"):
            command = binary / name
            command.write_text(script)
            command.chmod(0o755)

    def run_role(self, *, failure=None):
        (self.root / "fixture.json").write_text(json.dumps(self.fixture))
        role = Path(__file__).resolve().parents[1]
        play = [{
            "hosts": "localhost", "connection": "local", "gather_facts": False,
            "vars": {
                "ansible_hostname": "node-a", "proxmox_node": "node-a",
                "proxmox_pool": "test-pool", "proxmox_guest_startup": self.entries,
            },
            "tasks": [{"ansible.builtin.include_role": {"name": str(role)}}],
        }]
        path = self.root / "play.yml"
        path.write_text(yaml.safe_dump(play, sort_keys=False))
        env = {
            key: os.environ[key]
            for key in ("PATH", "LANG", "LC_ALL") if key in os.environ
        }
        env.update({
            "HOME": str(self.root),
            "PATH": str(self.root / "bin") + os.pathsep + env.get("PATH", ""),
            "STARTUP_FIXTURE_DIR": str(self.root),
            "ANSIBLE_LOCAL_TEMP": str(self.root / "ansible-local"),
            "ANSIBLE_REMOTE_TEMP": str(self.root / "ansible-remote"),
            "ANSIBLE_PYTHON_INTERPRETER": sys.executable,
            "ANSIBLE_NOCOLOR": "1",
        })
        result = subprocess.run(
            ["ansible-playbook", "-i", "localhost,", str(path)],
            capture_output=True, text=True, env=env, timeout=60, check=False,
        )
        if failure:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(failure, result.stdout)
            self.assertIn("failed=1", result.stdout)
            self.assertFalse((self.root / "writes.jsonl").exists())
        else:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.fixture = json.loads((self.root / "fixture.json").read_text())

    def test_reconcile_then_repeat_without_another_write(self):
        self.run_role()
        writes = self.root / "writes.jsonl"
        first = writes.read_text()
        self.assertEqual(json.loads(first), ["set", "101", "--startup", "order=1,up=30,down=60"])
        self.run_role()
        self.assertEqual(writes.read_text(), first)

    def test_existing_equivalent_parameter_order_does_not_write(self):
        self.fixture["config"]["101"]["startup"] = "down=60,order=1,up=30"
        self.run_role()
        self.assertFalse((self.root / "writes.jsonl").exists())

    def test_wrong_node_refused(self):
        self.fixture["locations"][0]["node"] = "node-b"
        self.run_role(failure="Require every selected guest to belong")

    def test_wrong_pool_refused(self):
        self.fixture["pool"]["members"] = []
        self.run_role(failure="Require every selected guest to belong")

    def test_template_refused(self):
        self.fixture["config"]["101"]["template"] = 1
        self.run_role(failure="Refuse templates before changing")

    def test_duplicate_ids_refused(self):
        self.entries.append({"vm_id": 101, "order": 2})
        self.run_role(failure="Reject duplicate VM IDs")

    def test_later_invalid_guest_prevents_all_writes(self):
        self.entries.append({"vm_id": 102, "order": 2})
        self.fixture["locations"].append({"vmid": 102, "type": "qemu", "node": "node-b"})
        self.fixture["pool"]["members"].append({"vmid": 102, "type": "qemu"})
        self.run_role(failure="Require every selected guest to belong")


if __name__ == "__main__":
    unittest.main()

"""Exercise the real Ansible seal guards using disposable local fixtures."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


@unittest.skipUnless(shutil.which("ansible-playbook"), "Ansible is required")
class SealGuardTests(unittest.TestCase):
    def run_guard(
        self, *, existing: bool, cached: bool, different: bool = False
    ) -> bool:
        tasks_path = Path(__file__).resolve().parents[1] / "tasks" / "main.yml"
        names = {
            "Inspect the cached seal key",
            "Inspect the deployed seal key",
            "Inspect existing vault storage",
            "Refuse to replace the seal of an existing vault",
            "Verify the cached seal matches the deployed key",
        }
        tasks = [
            task
            for task in yaml.safe_load(tasks_path.read_text())
            if task.get("name") in names
        ]
        self.assertEqual(len(tasks), len(names))
        with tempfile.TemporaryDirectory(prefix="milkyway-seal-guard-") as directory:
            root = Path(directory)
            cache, remote = root / "cache", root / "remote"
            cache.mkdir()
            remote.mkdir()
            if existing:
                (remote / "seal").mkdir()
                (remote / "seal" / "unseal.key").write_text("0" * 64)
                (remote / "data").mkdir()
                (remote / "data" / "raft.db").write_text("synthetic fixture")
            if cached:
                (cache / "openbao_unseal_key").write_text(
                    ("1" if different else "0") * 64
                )
            play = [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "vars": {
                        "openbao_secrets_dir": str(cache),
                        "openbao_deploy_dir": str(remote),
                    },
                    "tasks": tasks,
                }
            ]
            playbook = root / "play.yml"
            playbook.write_text(yaml.safe_dump(play, sort_keys=False))
            environment = os.environ.copy()
            environment["ANSIBLE_LOCAL_TEMP"] = str(root / "ansible-local")
            environment["ANSIBLE_REMOTE_TEMP"] = str(root / "ansible-remote")
            result = subprocess.run(
                ["ansible-playbook", "-i", "localhost,", str(playbook)],
                capture_output=True,
                text=True,
                env=environment,
                timeout=60,
                check=False,
            )
            # Infrastructure/runtime errors must not masquerade as a rejected key.
            if result.returncode:
                self.assertIn(
                    "Refuse to replace the seal of an existing vault", result.stdout
                )
                self.assertIn("failed=1", result.stdout)
            return result.returncode == 0

    def test_fresh_vault_allows_initial_generation(self):
        self.assertTrue(self.run_guard(existing=False, cached=False))

    def test_existing_data_requires_original_cached_seal(self):
        self.assertFalse(self.run_guard(existing=True, cached=False))

    def test_wrong_cached_seal_is_rejected(self):
        self.assertFalse(self.run_guard(existing=True, cached=True, different=True))

    def test_matching_cached_seal_is_accepted(self):
        self.assertTrue(self.run_guard(existing=True, cached=True))


if __name__ == "__main__":
    unittest.main()

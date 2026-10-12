"""Run the real restart readiness task against an isolated synthetic HTTP API."""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml


@unittest.skipUnless(shutil.which("ansible-playbook"), "Ansible is required")
class RestartReadinessTests(unittest.TestCase):
    def run_readiness(self, *, initialized: bool, sealed: bool) -> bool:
        payload = {"initialized": initialized, "sealed": sealed}

        class SealStatusHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/v1/sys/seal-status":
                    self.send_error(404)
                    return
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        handlers_path = Path(__file__).resolve().parents[1] / "handlers" / "main.yml"
        handlers = yaml.safe_load(handlers_path.read_text())
        tasks = [
            dict(task)
            for task in handlers
            if task.get("name") == "Wait for the vault to become ready after a restart"
        ]
        self.assertEqual(len(tasks), 1)
        tasks[0].pop("listen")
        server = ThreadingHTTPServer(("127.0.0.1", 0), SealStatusHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(
                prefix="milkyway-bao-readiness-"
            ) as directory:
                root = Path(directory)
                play = [
                    {
                        "hosts": "localhost",
                        "connection": "local",
                        "gather_facts": False,
                        "vars": {
                            "openbao_port": server.server_port,
                            "openbao_ready_retries": 1,
                            "openbao_ready_delay": 0,
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
                if result.returncode:
                    self.assertIn('"initialized": true', result.stdout)
                    self.assertIn('"sealed": true', result.stdout)
                    self.assertIn("failed=1", result.stdout)
                return result.returncode == 0
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_first_boot_can_continue_to_initialization(self):
        self.assertTrue(self.run_readiness(initialized=False, sealed=True))

    def test_existing_unsealed_vault_is_ready(self):
        self.assertTrue(self.run_readiness(initialized=True, sealed=False))

    def test_existing_sealed_vault_is_not_ready(self):
        self.assertFalse(self.run_readiness(initialized=True, sealed=True))


if __name__ == "__main__":
    unittest.main()

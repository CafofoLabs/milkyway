"""Exercise bootstrap token selection and idempotence without a live vault."""

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
class BootstrapSeedTests(unittest.TestCase):
    def test_operational_extra_variable_cannot_replace_bootstrap_token(self):
        stored = {}
        requests = []

        class VaultHandler(BaseHTTPRequestHandler):
            def reply(self, status, payload):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def authorized(self):
                if self.headers.get("X-Vault-Token") != "SYNTHETIC_ROOT_TOKEN":
                    self.reply(403, {"errors": ["wrong fixture token"]})
                    return False
                return True

            def do_GET(self):
                requests.append("GET")
                if self.authorized():
                    self.reply(
                        200, {"data": {"data": stored}}
                    ) if stored else self.reply(404, {"errors": []})

            def do_POST(self):
                requests.append("POST")
                if self.authorized():
                    payload = json.loads(
                        self.rfile.read(int(self.headers["Content-Length"]))
                    )
                    stored.update(payload["data"])
                    self.reply(200, {"data": {"version": 1}})

            def log_message(self, *_args):
                pass

        tasks_path = Path(__file__).resolve().parents[1] / "tasks" / "seed.yml"
        tasks = yaml.safe_load(tasks_path.read_text())
        server = ThreadingHTTPServer(("127.0.0.1", 0), VaultHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="milkyway-seed-") as directory:
                root = Path(directory)
                token = root / "bootstrap-token"
                credential = root / "external-credential"
                token.write_text("SYNTHETIC_ROOT_TOKEN")
                credential.write_text("SYNTHETIC_EXTERNAL_CREDENTIAL")
                for task in tasks:
                    if "ansible.builtin.uri" in task:
                        # Keep the real task headers/body/conditions. Only transport
                        # points at an isolated HTTP fixture instead of live TLS.
                        task["ansible.builtin.uri"]["url"] = (
                            f"http://127.0.0.1:{server.server_port}/v1/secret/data/fixture"
                        )
                playbook = root / "play.yml"
                playbook.write_text(
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
                variables = root / "vars.json"
                variables.write_text(
                    json.dumps(
                        {
                            "platform_access_mode": "bootstrap",
                            "platform_bao_addr": "https://synthetic.invalid",
                            # Extra vars outrank include_role vars. This file
                            # deliberately does not exist on first boot.
                            "platform_bao_token_file": str(root / "absent-ops-token"),
                            "platform_bootstrap_bao_token_file": str(token),
                            "platform_bootstrap_secrets": [
                                {
                                    "path": "platform/tailscale/auth_key",
                                    "field": "key",
                                    "file": str(credential),
                                }
                            ],
                        }
                    )
                )
                environment = os.environ.copy()
                environment["ANSIBLE_LOCAL_TEMP"] = str(root / "ansible-local")
                environment["ANSIBLE_REMOTE_TEMP"] = str(root / "ansible-remote")
                for _ in range(2):
                    result = subprocess.run(
                        [
                            "ansible-playbook",
                            "-i",
                            "localhost,",
                            str(playbook),
                            "-e",
                            "@" + str(variables),
                        ],
                        capture_output=True,
                        text=True,
                        env=environment,
                        timeout=60,
                        check=False,
                    )
                    self.assertEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )
                self.assertEqual(requests, ["GET", "POST", "GET"])
                self.assertEqual(stored, {"key": "SYNTHETIC_EXTERNAL_CREDENTIAL"})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()

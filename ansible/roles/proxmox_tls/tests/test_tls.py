"""Exercise native TLS reconciliation using disposable certificates and commands."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import jinja2
import pytest

ROLE = Path(__file__).resolve().parents[1]
OPENSSL = shutil.which("openssl")
pytestmark = pytest.mark.skipif(not OPENSSL, reason="OpenSSL is required")


def command(arguments: list[str]) -> None:
    result = subprocess.run(arguments, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, "Disposable certificate setup failed"


def executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o750)


@pytest.fixture(scope="module")
def certificates(tmp_path_factory):
    root = tmp_path_factory.mktemp("tls-certificate-fixtures")
    ca = root / "ca"
    ca.mkdir()
    command(
        [
            OPENSSL,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(root / "root.key"),
            "-out",
            str(ca / "root.crt"),
            "-days",
            "2",
            "-subj",
            "/CN=Disposable Test Root",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
        ]
    )
    command([OPENSSL, "rehash", str(ca)])
    command(
        [
            OPENSSL,
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(root / "leaf.key"),
            "-out",
            str(root / "leaf.csr"),
            "-subj",
            "/CN=node.example.test",
        ]
    )
    (root / "leaf.ext").write_text(
        "subjectAltName=DNS:node.example.test\n"
        "extendedKeyUsage=serverAuth\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        "basicConstraints=critical,CA:FALSE\n"
    )
    command(
        [
            OPENSSL,
            "x509",
            "-req",
            "-in",
            str(root / "leaf.csr"),
            "-CA",
            str(ca / "root.crt"),
            "-CAkey",
            str(root / "root.key"),
            "-CAcreateserial",
            "-out",
            str(root / "leaf.crt"),
            "-days",
            "2",
            "-sha256",
            "-extfile",
            str(root / "leaf.ext"),
        ]
    )
    return root


class Reconciliation:
    def __init__(self, root: Path, certificates: Path):
        self.root = root
        self.certificates = certificates
        self.bin = root / "bin"
        self.bin.mkdir()
        self.state = root / "state"
        (self.state / "certificates").mkdir(parents=True)
        self.installed = root / "installed.crt"
        self.served = root / "served.crt"
        self.token = root / "opaque-token-file"
        self.token.touch(mode=0o600)
        self.issued = self.state / "certificates" / "node.example.test.crt"
        self.key = self.state / "certificates" / "node.example.test.key"
        shutil.copyfile(certificates / "leaf.crt", self.issued)
        shutil.copyfile(certificates / "leaf.key", self.key)
        self.context = {
            "proxmox_tls_lock_file": str(root / "tls.lock"),
            "proxmox_tls_binary_dir": str(self.bin),
            "proxmox_tls_state_dir": str(self.state),
            "acme_email": "operator@example.test",
            "proxmox_tls_ca_servers": {
                "production": "https://acme.example.test/production",
                "staging": "https://acme.example.test/staging",
            },
            "proxmox_tls_ca_environment": "production",
            "proxmox_tls_fqdn": "node.example.test",
            "acme_dns_resolvers": "ns1.example.test:53,ns2.example.test:53",
            "proxmox_tls_installed_certificate": str(self.installed),
            "proxmox_tls_ca_path": str(certificates / "ca"),
        }
        self.environment = {
            key: os.environ[key]
            for key in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")
            if key in os.environ
        }
        self.environment.update(
            {
                "PATH": f"{self.bin}:{self.environment.get('PATH', '')}",
                "HOME": str(root),
                "HOSTINGER_API_TOKEN_FILE": str(self.token),
                "TLS_FIXTURE_ROOT": str(root),
                "TLS_FIXTURE_OPENSSL": OPENSSL,
            }
        )
        executable(self.bin / "flock", "#!/bin/sh\nexit 0\n")
        executable(self.bin / "timeout", '#!/bin/sh\nshift\nexec "$@"\n')
        executable(self.bin / "sleep", "#!/bin/sh\nexit 0\n")
        executable(
            self.bin / "lego",
            f"#!{sys.executable}\n"
            + r"""
import json, os, pathlib, sys
root = pathlib.Path(os.environ["TLS_FIXTURE_ROOT"])
with (root / "lego.calls").open("a") as output:
    output.write(json.dumps(sys.argv[1:]) + "\n")
if os.environ.get("TLS_FIXTURE_ISSUE_FAILURE"):
    print("opaque third-party response", file=sys.stderr)
    sys.exit(1)
""",
        )
        executable(
            self.bin / "pvenode",
            f"#!{sys.executable}\n"
            + r"""
import json, os, pathlib, shutil, sys
root = pathlib.Path(os.environ["TLS_FIXTURE_ROOT"])
with (root / "pvenode.calls").open("a") as output:
    output.write(json.dumps(sys.argv[1:]) + "\n")
if os.environ.get("TLS_FIXTURE_INSTALL_FAILURE") == "before":
    sys.exit(1)
shutil.copyfile(sys.argv[3], root / "installed.crt")
if os.environ.get("TLS_FIXTURE_INSTALL_FAILURE") == "after":
    sys.exit(1)
if not os.environ.get("TLS_FIXTURE_PROXY_FAILURE"):
    shutil.copyfile(sys.argv[3], root / "served.crt")
""",
        )
        executable(
            self.bin / "openssl",
            f"#!{sys.executable}\n"
            + r"""
import os, pathlib, sys
if sys.argv[1] == "s_client":
    served = pathlib.Path(os.environ["TLS_FIXTURE_ROOT"]) / "served.crt"
    if not served.exists():
        sys.exit(1)
    sys.stdout.buffer.write(served.read_bytes())
else:
    binary = os.environ["TLS_FIXTURE_OPENSSL"]
    os.execv(binary, [binary, *sys.argv[1:]])
""",
        )

    def run(self, **environment):
        template = jinja2.Environment(undefined=jinja2.StrictUndefined)
        template.filters["quote"] = shlex.quote
        script = self.root / "reconcile.sh"
        executable(
            script,
            template.from_string(
                (ROLE / "templates" / "reconcile.sh.j2").read_text()
            ).render(**self.context),
        )
        command(["/bin/bash", "-n", str(script)])
        return subprocess.run(
            ["/bin/bash", str(script)],
            env=self.environment | environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def calls(self, name):
        path = self.root / f"{name}.calls"
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if path.exists()
            else []
        )


@pytest.fixture
def reconcile(tmp_path, certificates):
    return Reconciliation(tmp_path, certificates)


def test_first_install_then_repeat_does_not_restart(reconcile):
    assert reconcile.run().returncode == 0
    assert reconcile.run().returncode == 0
    assert len(reconcile.calls("pvenode")) == 1
    assert reconcile.calls("pvenode")[0][-4:] == ["--force", "1", "--restart", "1"]
    arguments = reconcile.calls("lego")[0]
    assert arguments[0] == "run"
    assert "--dns.resolvers" in arguments
    assert "--renew-force" not in arguments
    assert str(reconcile.token) not in arguments


def test_failed_issuance_preserves_installed_certificate(reconcile):
    shutil.copyfile(reconcile.issued, reconcile.installed)
    before = reconcile.installed.read_bytes()  # Public certificate only.
    result = reconcile.run(TLS_FIXTURE_ISSUE_FAILURE="1")
    assert result.returncode != 0
    assert reconcile.installed.read_bytes() == before
    assert reconcile.calls("pvenode") == []
    assert "opaque third-party response" not in result.stderr


def test_failed_install_retries_existing_certificate(reconcile):
    assert reconcile.run(TLS_FIXTURE_INSTALL_FAILURE="before").returncode != 0
    assert reconcile.run().returncode == 0
    assert len(reconcile.calls("pvenode")) == 2


def test_failed_reload_retries_even_when_files_already_match(reconcile):
    assert reconcile.run(TLS_FIXTURE_INSTALL_FAILURE="after").returncode != 0
    assert reconcile.installed.exists()
    assert reconcile.run().returncode == 0
    assert len(reconcile.calls("pvenode")) == 2


def test_missing_installed_file_is_repaired(reconcile):
    assert reconcile.run().returncode == 0
    reconcile.installed.unlink()
    assert reconcile.run().returncode == 0
    assert len(reconcile.calls("pvenode")) == 2


def test_wrong_hostname_never_reaches_proxmox(reconcile):
    reconcile.context["proxmox_tls_fqdn"] = "wrong.example.test"
    shutil.copyfile(
        reconcile.issued, reconcile.issued.with_name("wrong.example.test.crt")
    )
    shutil.copyfile(reconcile.key, reconcile.key.with_name("wrong.example.test.key"))
    assert reconcile.run().returncode != 0
    assert reconcile.calls("pvenode") == []


def test_mismatched_private_key_never_reaches_proxmox(reconcile):
    shutil.copyfile(reconcile.certificates / "root.key", reconcile.key)
    assert reconcile.run().returncode != 0
    assert reconcile.calls("pvenode") == []


def test_untrusted_chain_never_reaches_proxmox(reconcile):
    empty = reconcile.root / "empty-ca"
    empty.mkdir()
    reconcile.context["proxmox_tls_ca_path"] = str(empty)
    assert reconcile.run().returncode != 0
    assert reconcile.calls("pvenode") == []


def test_proxy_verification_failure_is_reported(reconcile):
    assert reconcile.run(TLS_FIXTURE_PROXY_FAILURE="1").returncode != 0
    assert reconcile.run().returncode == 0
    assert len(reconcile.calls("pvenode")) == 2


def test_staging_never_installs_or_reloads_proxmox(reconcile):
    reconcile.context["proxmox_tls_ca_environment"] = "staging"
    assert reconcile.run().returncode == 0
    assert reconcile.calls("pvenode") == []
    assert "https://acme.example.test/staging" in reconcile.calls("lego")[0]


def test_missing_opaque_credential_fails_before_issuance(reconcile):
    reconcile.token.unlink()
    assert reconcile.run().returncode != 0
    assert reconcile.calls("lego") == []
    assert reconcile.calls("pvenode") == []

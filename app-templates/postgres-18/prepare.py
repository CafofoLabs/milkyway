"""Create a password on the worker without returning or replacing its value."""

import os
import re
import socket
import subprocess
import tempfile
from pathlib import Path

name = os.environ["MAPPED_APP_NAME"]
worker = os.environ["MAPPED_APP_WORKER"]
if os.geteuid() != 0 or socket.gethostname().split(".")[0] != worker:
    raise SystemExit("Run as root on the declared worker")
if not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", name):
    raise SystemExit("Invalid application name")
directory = Path("/etc/nimbus/secrets")
password = directory / f"{name}-password"
for path in (directory.parent, directory, password):
    if path.is_symlink():
        raise SystemExit("Refusing a symlink in the password path")
changed = False
if not password.exists():
    volume = subprocess.run(
        ["docker", "volume", "inspect", f"{name}_postgres_data"],
        capture_output=True,
        check=False,
    )
    if volume.returncode == 0:
        raise SystemExit("Existing data has no password file; recover it instead")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{name}-", dir=directory)
    os.close(descriptor)
    try:
        subprocess.run(["openssl", "rand", "-hex", "-out", temporary, "32"], check=True)
        os.chown(temporary, 999, 999)
        os.chmod(temporary, 0o400)
        os.replace(temporary, password)
    finally:
        Path(temporary).unlink(missing_ok=True)
    changed = True
state = password.stat()
if (
    not password.is_file()
    or not state.st_size
    or (state.st_uid, state.st_gid, state.st_mode & 0o777) != (999, 999, 0o400)
):
    raise SystemExit(
        "Expected a protected nonempty password owned by 999:999, mode 0400"
    )
print(f"changed={str(changed).lower()}")

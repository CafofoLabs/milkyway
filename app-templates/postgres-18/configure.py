"""Install only explicitly requested extensions using PostgreSQL identifiers."""

import json
import os
import re
import subprocess

parameters = json.loads(os.environ["MAPPED_APP_PARAMETERS"])
changed = False
for extension in parameters["extensions"]:
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", extension):
        raise SystemExit("Invalid extension identifier")
    base = [
        "docker",
        "compose",
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        parameters["user"],
        "-d",
        "postgres",
        "-At",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
    ]
    installed = subprocess.check_output(
        base
        + [f"SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='{extension}')"],
        text=True,
    ).strip()
    if installed != "t":
        subprocess.run(base + [f'CREATE EXTENSION "{extension}"'], check=True)
        changed = True
print(f"changed={str(changed).lower()}")

"""Check public database facts and preserve the instance's original volume."""

import json
import os
import subprocess

name = os.environ["MAPPED_APP_NAME"]
parameters = json.loads(os.environ["MAPPED_APP_PARAMETERS"])
container = subprocess.check_output(
    ["docker", "compose", "ps", "-q", "postgres"], text=True
).strip()
volume = subprocess.check_output(
    [
        "docker",
        "inspect",
        "--format",
        '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql"}}{{.Name}}{{end}}{{end}}',
        container,
    ],
    text=True,
).strip()
if volume != f"{name}_postgres_data":
    raise SystemExit("Unexpected database data volume")
facts = json.loads(
    subprocess.check_output(
        [
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
            "SELECT json_build_object('major', current_setting('server_version_num')::int / 10000, 'user', current_user, 'dba', (SELECT rolsuper FROM pg_roles WHERE rolname=current_user), 'password_configured', (SELECT rolpassword IS NOT NULL FROM pg_authid WHERE rolname=current_user), 'extensions', (SELECT json_agg(extname) FROM pg_extension))",
        ],
        text=True,
    )
)
if (
    facts["major"] != 18
    or facts["user"] != parameters["user"]
    or facts["dba"] != parameters["dba"]
    or not facts["password_configured"]
    or not set(parameters["extensions"]).issubset(facts["extensions"])
):
    raise SystemExit("Database does not match the declared parameters")
print(json.dumps(facts))

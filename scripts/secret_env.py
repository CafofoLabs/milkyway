"""Fetch authorized KV v2 bindings and exec one process; never print values."""

import argparse
import json
import os
import re
import syslog
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, build_opener

from service_identity_runtime import (
    AuthenticationError,
    NoRedirect,
    authenticate,
    protected_load,
    request,
)


def bindings(document):
    if not isinstance(document, dict) or set(document) != {
        "env",
        "secret_env",
        "account",
    }:
        raise AuthenticationError("Invalid environment binding document")
    if not isinstance(document["env"], dict) or not isinstance(
        document["secret_env"], dict
    ):
        raise AuthenticationError("Invalid environment mappings")
    if document["env"].keys() & document["secret_env"].keys():
        raise AuthenticationError("Conflicting environment bindings")
    for key in document["env"] | document["secret_env"]:
        if (
            not re.fullmatch(r"[A-Z][A-Z0-9_]*", key)
            or key in {"HOME", "USER", "SHELL", "PATH", "HERMES_HOME"}
            or key.startswith(("LD_", "DYLD_", "PYTHON", "MILKYWAY_"))
        ):
            raise AuthenticationError("Unsupported environment variable")
    for value in document["env"].values():
        if not isinstance(value, str) or "\x00" in value:
            raise AuthenticationError("Invalid environment value")
    for reference in document["secret_env"].values():
        if (
            not isinstance(reference, dict)
            or set(reference) != {"mount", "path", "key"}
            or any(not isinstance(v, str) or not v for v in reference.values())
        ):
            raise AuthenticationError("Invalid secret reference")
        if (
            any(
                not re.fullmatch(r"[A-Za-z0-9_-]+", part)
                for field in ("mount", "path", "key")
                for part in reference[field].split("/")
            )
            or "/" in reference["mount"]
            or "/" in reference["key"]
        ):
            raise AuthenticationError("Secret references require literal paths")
    return document


def read_secret(connection, token, reference):
    url = (
        connection["vault_url"]
        + "/v1/"
        + quote(reference["mount"], safe="")
        + "/data/"
        + quote(reference["path"], safe="/")
    )
    try:
        response = build_opener(NoRedirect()).open(
            Request(url, headers={"X-Vault-Token": token}), timeout=30
        )
        with response:
            return json.load(response)["data"]["data"]
    except (OSError, ValueError, KeyError, TypeError):
        raise AuthenticationError("Required secret read failed") from None


def resolve(document, deployment):
    bindings(document)
    if not document["secret_env"]:
        return dict(document["env"])
    account = deployment["accounts"][document["account"]]
    session = authenticate(deployment["connection"], account)
    token = session["client_token"]
    resolved = dict(document["env"])
    cache = {}
    try:
        for variable, reference in document["secret_env"].items():
            key = (reference["mount"], reference["path"])
            if key not in cache:
                cache[key] = read_secret(deployment["connection"], token, reference)
            value = cache[key].get(reference["key"])
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise AuthenticationError("A required secret field is unavailable")
            resolved[variable] = value
    finally:
        request(
            deployment["connection"]["vault_url"] + "/v1/auth/token/revoke-self",
            {},
            token,
        )
    return resolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        document = json.loads(args.bindings.read_text())
        values = resolve(
            document,
            protected_load(args.credentials) if document["secret_env"] else None,
        )
        if args.check:
            print("Required runtime bindings verified; values suppressed.")
            return
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command or not Path(command[0]).is_absolute():
            raise AuthenticationError("An absolute executable is required")
        # Do not inherit provisioning credentials or stale provider overrides.
        env = {
            key: os.environ[key]
            for key in (
                "HOME",
                "USER",
                "LOGNAME",
                "PATH",
                "LANG",
                "LC_ALL",
                "HERMES_HOME",
            )
            if key in os.environ
        }
        env.update(values)
        syslog.openlog("milkyway-secrets")
        syslog.syslog(syslog.LOG_INFO, "Runtime bindings resolved; starting workload")
        os.execve(command[0], command, env)
    except Exception:  # noqa: BLE001 -- unexpected credential errors must never disclose values
        syslog.openlog("milkyway-secrets")
        syslog.syslog(
            syslog.LOG_ERR, "Runtime bindings unavailable; workload not started"
        )
        parser.exit(
            1, "Runtime secret resolution failed; credential diagnostics suppressed.\n"
        )


if __name__ == "__main__":
    main()

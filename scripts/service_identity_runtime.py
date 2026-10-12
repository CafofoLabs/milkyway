"""Reference M2M client: Authentik app password -> signed JWT -> OpenBao token.

Applications may use their standard HTTP/OpenBao libraries instead. No Nimbus
process is required at runtime. This executable writes a token file, never stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class AuthenticationError(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AuthenticationError("Authentication redirects are refused")


def request(url, payload, token=None, form=False):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise AuthenticationError("Authentication requires a trusted HTTPS endpoint")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
        if form
        else "application/json"
    }
    if token is not None:
        headers["X-Vault-Token"] = token
    body = urlencode(payload).encode() if form else json.dumps(payload).encode()
    try:
        with build_opener(NoRedirect()).open(
            Request(url, data=body, headers=headers), timeout=30
        ) as response:
            content = response.read()
            return json.loads(content) if content else {}
    except (HTTPError, URLError, ValueError) as error:
        raise AuthenticationError(
            "Authentication or authorization request failed"
        ) from error


def authenticate(connection, account):
    jwt = request(
        connection["token_url"],
        {
            "grant_type": "client_credentials",
            "client_id": connection["client_id"],
            "username": account["username"],
            "password": account["password"],
            "scope": connection["scope"],
        },
        form=True,
    )["access_token"]
    session = request(
        connection["vault_url"] + "/v1/auth/" + connection["auth_mount"] + "/login",
        {"role": account["role"], "jwt": jwt},
    )["auth"]
    return session


def protected_load(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as source:
        info = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_uid != os.getuid()
        ):
            raise AuthenticationError(
                "Deployment credentials require a private owned regular file"
            )
        return json.load(source)


def verify(path, contract):
    deployment = protected_load(path)
    expected = {
        name for name, account in contract["accounts"].items() if account["enabled"]
    }
    if set(deployment["accounts"]) != expected:
        raise AuthenticationError(
            "Deployment artifacts do not match the enabled accounts"
        )
    connection = deployment["connection"]
    for name, account in deployment["accounts"].items():
        session = authenticate(connection, account)
        token = session["client_token"]
        base = connection["vault_url"] + "/v1/"
        try:
            reads = contract["accounts"][name]["reads"]
            paths = {f"{r['mount']}/data/{r['path']}" for r in reads}
            paths.update(
                f"{r['mount']}/data/{r['path']}/__milkyway_probe__"
                for r in reads
                if r["recursive"]
            )
            denied = {
                "sys/mounts",
                "secret/data/platform/__milkyway_probe__",
                "secret/data/apps/__milkyway_unrelated__",
            }
            response = request(
                base + "sys/capabilities-self", {"paths": sorted(paths | denied)}, token
            )
            capabilities = response.get("data", response)
            for secret_path in paths:
                if set(capabilities.get(secret_path, [])) != {"read"}:
                    raise AuthenticationError(
                        "Expected read-only permission was not verified"
                    )
                metadata = secret_path.replace("/data/", "/metadata/", 1)
                response = request(
                    base + "sys/capabilities-self", {"paths": [metadata]}, token
                )
                result = response.get("data", response)
                if result.get(metadata, result.get("capabilities")) != ["deny"]:
                    raise AuthenticationError("Unexpected secret metadata access")
            if any(capabilities.get(p) != ["deny"] for p in denied):
                raise AuthenticationError(
                    "Unexpected infrastructure or unrelated app permission"
                )
        finally:
            request(base + "auth/token/revoke-self", {}, token)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        deployment = protected_load(args.credentials)
        session = authenticate(
            deployment["connection"], deployment["accounts"][args.account]
        )
        descriptor = os.open(
            args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "w") as target:
            os.fchmod(target.fileno(), 0o600)
            json.dump(session, target)
    except (AuthenticationError, OSError, ValueError, KeyError):
        parser.exit(
            1, "Machine authentication failed; credential output is suppressed.\n"
        )


if __name__ == "__main__":
    main()

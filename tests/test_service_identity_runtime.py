"""Reference-client protocol and verification tests with synthetic HTTP responses."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import service_identity_runtime as runtime


def test_runtime_uses_named_account_not_provider_secret(monkeypatch):
    calls = []

    def request(url, payload, token=None, form=False):
        calls.append((url, payload, form))
        if form:
            return {"access_token": "synthetic-jwt"}
        return {"auth": {"client_token": "synthetic-bao-token", "lease_duration": 300}}

    monkeypatch.setattr(runtime, "request", request)
    connection = {
        "token_url": "https://idp.example.test/application/o/token/",
        "client_id": "services",
        "scope": "milkyway-service",
        "vault_url": "https://bao.example.test",
        "auth_mount": "service-jwt",
    }
    runtime.authenticate(
        connection,
        {
            "username": "svc-inventory-dev",
            "password": "synthetic-only",
            "role": "inventory",
        },
    )
    assert calls[0][1]["username"] == "svc-inventory-dev"
    assert "client_secret" not in calls[0][1]
    assert calls[1][1] == {"role": "inventory", "jwt": "synthetic-jwt"}


def test_rejects_unprotected_credentials(tmp_path):
    source = tmp_path / "credentials.json"
    source.write_text("{}")
    source.chmod(0o644)
    with pytest.raises(runtime.AuthenticationError):
        runtime.protected_load(source)
    source.chmod(0o600)
    assert runtime.protected_load(source) == {}


@pytest.mark.parametrize(
    "url",
    ["http://idp.example.test/token", "https://user:password@idp.example.test/token"],
)
def test_refuses_insecure_or_credentialed_endpoints(url):
    with pytest.raises(runtime.AuthenticationError):
        runtime.request(url, {})


def test_refuses_redirects():
    with pytest.raises(runtime.AuthenticationError):
        runtime.NoRedirect().redirect_request(
            None, None, 302, "", {}, "https://elsewhere.test"
        )


@pytest.mark.parametrize(
    "capabilities", [["read"], ["read", "update"], ["read", "list"], ["deny"]]
)
def test_verify_checks_effective_permissions_and_always_revokes(
    tmp_path, monkeypatch, capabilities
):
    source = tmp_path / "credentials.json"
    source.write_text(
        json.dumps(
            {
                "connection": {"vault_url": "https://bao.example.test"},
                "accounts": {"svc-inventory-dev": {}},
            }
        )
    )
    source.chmod(0o600)
    revoked = []
    monkeypatch.setattr(
        runtime, "authenticate", lambda *args: {"client_token": "synthetic"}
    )

    def request(url, payload, token=None):
        if url.endswith("revoke-self"):
            revoked.append(True)
            return {}
        return {
            "data": {
                p: capabilities if "/data/apps/inventory/dev" in p else ["deny"]
                for p in payload["paths"]
            }
        }

    monkeypatch.setattr(runtime, "request", request)
    contract = {
        "accounts": {
            "svc-inventory-dev": {
                "enabled": True,
                "reads": [
                    {"mount": "secret", "path": "apps/inventory/dev", "recursive": True}
                ],
            }
        }
    }
    if capabilities == ["read"]:
        runtime.verify(source, contract)
    else:
        with pytest.raises(runtime.AuthenticationError):
            runtime.verify(source, contract)
    assert revoked == [True]


def test_successful_empty_revoke_response_is_accepted(monkeypatch):
    from io import BytesIO

    class Opener:
        def open(self, *args, **kwargs):
            return BytesIO(b"")

    monkeypatch.setattr(runtime, "build_opener", lambda *args: Opener())
    assert (
        runtime.request("https://bao.example.test/v1/auth/token/revoke-self", {}) == {}
    )

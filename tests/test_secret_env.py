"""Runtime secrets fail closed, revoke short-lived tokens and never reach output."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import secret_env


def document():
    return {
        "env": {"HERMES_TIMEZONE": "UTC"},
        "secret_env": {
            "OLLAMA_API_KEY": {
                "mount": "secret",
                "path": "apps/hermes/prod/first/ollama",
                "key": "api_key",
            }
        },
        "account": "svc-hermes-prod-first",
    }


def deployment():
    return {
        "connection": {"vault_url": "https://bao.example.test"},
        "accounts": {"svc-hermes-prod-first": {"password": "synthetic-identity-only"}},
    }


def fake_auth(monkeypatch):
    calls = []
    monkeypatch.setattr(
        secret_env, "authenticate", lambda *a: {"client_token": "synthetic-token-only"}
    )
    monkeypatch.setattr(secret_env, "request", lambda *a: calls.append(a))
    return calls


def test_success_and_new_value_after_rotation(monkeypatch, capsys):
    calls = fake_auth(monkeypatch)
    values = iter(["synthetic-first", "synthetic-rotated"])
    monkeypatch.setattr(secret_env, "read_secret", lambda *a: {"api_key": next(values)})
    assert (
        secret_env.resolve(document(), deployment())["OLLAMA_API_KEY"]
        == "synthetic-first"
    )
    assert (
        secret_env.resolve(document(), deployment())["OLLAMA_API_KEY"]
        == "synthetic-rotated"
    )
    assert len(calls) == 2 and calls[0][0].endswith("auth/token/revoke-self")
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("value", [None, "", "  ", 42, "invalid\x00value"])
def test_missing_or_invalid_secret_is_fatal_and_token_revoked(monkeypatch, value):
    calls = fake_auth(monkeypatch)
    monkeypatch.setattr(secret_env, "read_secret", lambda *a: {"api_key": value})
    with pytest.raises(ValueError, match="unavailable"):
        secret_env.resolve(document(), deployment())
    assert len(calls) == 1


def test_duplicate_path_fetches_once(monkeypatch):
    fake_auth(monkeypatch)
    calls = []
    monkeypatch.setattr(
        secret_env,
        "read_secret",
        lambda *a: calls.append(a) or {"api_key": "synthetic-only"},
    )
    inputs = document()
    inputs["secret_env"]["OTHER_API_KEY"] = inputs["secret_env"]["OLLAMA_API_KEY"]
    assert len(secret_env.resolve(inputs, deployment())) == 3
    assert len(calls) == 1


def test_secretless_login_does_not_read_machine_credentials(
    monkeypatch, tmp_path, capsys
):
    config = tmp_path / "bindings.json"
    inputs = document()
    inputs["secret_env"] = {}
    config.write_text(json.dumps(inputs))
    monkeypatch.setattr(
        secret_env,
        "protected_load",
        lambda *a: pytest.fail("No machine credential is needed for public bindings"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "secret_env.py",
            "--bindings",
            str(config),
            "--credentials",
            str(tmp_path / "missing.json"),
            "--check",
        ],
    )
    secret_env.main()
    assert (
        capsys.readouterr().out
        == "Required runtime bindings verified; values suppressed.\n"
    )


def test_failure_never_executes_or_discloses_provider_diagnostics(
    monkeypatch, tmp_path, capsys
):
    config = tmp_path / "bindings.json"
    config.write_text(json.dumps(document()))
    credentials = tmp_path / "identity.json"
    credentials.write_text(json.dumps(deployment()))
    credentials.chmod(0o600)
    fake_auth(monkeypatch)
    monkeypatch.setattr(
        secret_env,
        "read_secret",
        lambda *a: (_ for _ in ()).throw(ValueError("synthetic-sensitive-diagnostic")),
    )
    monkeypatch.setattr(
        secret_env.os,
        "execve",
        lambda *a: pytest.fail("Must not start without every required binding"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "secret_env.py",
            "--bindings",
            str(config),
            "--credentials",
            str(credentials),
            "--",
            "/bin/true",
        ],
    )
    with pytest.raises(SystemExit) as result:
        secret_env.main()
    assert result.value.code == 1
    output = capsys.readouterr()
    assert "synthetic-sensitive" not in output.out + output.err


def test_runtime_exec_drops_provisioning_and_stale_provider_environment(
    monkeypatch, tmp_path
):
    config = tmp_path / "bindings.json"
    config.write_text(json.dumps(document()))
    credentials = tmp_path / "identity.json"
    credentials.write_text(json.dumps(deployment()))
    credentials.chmod(0o600)
    fake_auth(monkeypatch)
    monkeypatch.setattr(
        secret_env, "read_secret", lambda *a: {"api_key": "synthetic-runtime-only"}
    )
    monkeypatch.setenv("VAULT_TOKEN", "synthetic-provisioning-only")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-stale-only")
    monkeypatch.setenv("OLLAMA_API_KEY", "synthetic-old-only")
    executed = []
    monkeypatch.setattr(secret_env.os, "execve", lambda *a: executed.append(a))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "secret_env.py",
            "--bindings",
            str(config),
            "--credentials",
            str(credentials),
            "--",
            "/bin/true",
        ],
    )
    secret_env.main()
    environment = executed[0][2]
    assert "VAULT_TOKEN" not in environment and "OPENAI_API_KEY" not in environment
    assert environment["OLLAMA_API_KEY"] == "synthetic-runtime-only"

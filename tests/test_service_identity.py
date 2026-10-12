"""Contract, ownership and saved-plan safety tests; no live secrets or services."""

import copy
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "service_identity", ROOT / "scripts/service_identity.py"
)
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


@pytest.fixture
def config():
    return identity.catalog(
        identity.load(ROOT / "examples/service-accounts/catalog.yaml")
    )


@pytest.fixture
def manifest():
    return identity.load(ROOT / "examples/service-accounts/inventory.yaml")


def test_contract_and_catalog_allow_only_declared_paths(config, manifest):
    result = identity.compile_contract(manifest, config)
    assert result["accounts"]["svc-inventory-dev"]["reads"][1]["path"] == "shared/mail"
    assert result["profiles"] == {"application-service": {"policies": []}}


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", True),
        ("version", 2),
        ("databases", []),
        ("application", "../platform"),
        ("environment", "unknown"),
        ("serviceAccounts", {}),
    ],
)
def test_rejects_unknown_unsupported_and_unregistered_inputs(
    config, manifest, field, value
):
    manifest[field] = value
    with pytest.raises(identity.ContractError):
        identity.compile_contract(manifest, config)


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "akadmin"),
        ("name", "svc-other-dev"),
        ("enabled", "false"),
        ("credentialRevision", True),
        ("credentialRevision", 0),
        ("roles", ["platform-admin"]),
        ("roles", ["application-service"] * 2),
        ("password", "unsupported"),
        ("databases", []),
    ],
)
def test_rejects_account_privilege_escalation(config, manifest, field, value):
    manifest["serviceAccounts"][0][field] = value
    with pytest.raises(identity.ContractError):
        identity.compile_contract(manifest, config)


@pytest.mark.parametrize(
    "path,recursive",
    [
        ("apps/inventory", True),
        ("apps/inventory/development", True),
        ("apps/inventory/dev/../prod", False),
        ("apps/inventory/dev/*", False),
        ("shared/mail", True),
        ("platform/admin", False),
        ("", False),
        ("apps/inventory/dev/", False),
        ("apps/inventory/dev//key", False),
    ],
)
def test_secret_boundaries(config, manifest, path, recursive):
    manifest["serviceAccounts"][0]["secrets"]["read"] = [
        {"mount": "secret", "path": path, "recursive": recursive}
    ]
    with pytest.raises(identity.ContractError):
        identity.compile_contract(manifest, config)


def test_duplicate_yaml_keys_are_rejected(tmp_path):
    source = tmp_path / "request.yaml"
    source.write_text("version: 1\nversion: 2\n")
    with pytest.raises(identity.ContractError):
        identity.load(source)


def test_duplicate_accounts_and_rules_are_rejected(config, manifest):
    manifest["serviceAccounts"] *= 2
    with pytest.raises(identity.ContractError):
        identity.compile_contract(manifest, config)
    manifest["serviceAccounts"] = manifest["serviceAccounts"][:1]
    manifest["serviceAccounts"][0]["secrets"]["read"] *= 2
    with pytest.raises(identity.ContractError):
        identity.compile_contract(manifest, config)


def test_two_generic_consumers_do_not_share_endpoints_or_ownership(config, manifest):
    first = identity.compile_contract(manifest, config)
    second = copy.deepcopy(config)
    second["deployment"] = "second"
    second["identity"]["url"] = "https://identity.second.test"
    second["openbao"]["url"] = "https://bao.second.test"
    assert (
        first["deployment"]
        != identity.compile_contract(manifest, identity.catalog(second))["deployment"]
    )
    assert (
        identity.settings(config)["identity_url"]
        != identity.settings(second)["identity_url"]
    )
    other = copy.deepcopy(manifest)
    other["application"] = "billing"
    other["serviceAccounts"][0]["name"] = "svc-billing-dev"
    other["serviceAccounts"][0]["secrets"]["read"] = []
    config["applications"]["billing"] = {
        "dev": {"roles": ["application-service"], "secrets": []}
    }
    assert (
        first["application"] != identity.compile_contract(other, config)["application"]
    )


def test_multiple_accounts_and_explicit_disable(config, manifest):
    account = copy.deepcopy(manifest["serviceAccounts"][0])
    account["name"] += "-worker"
    account["enabled"] = False
    manifest["serviceAccounts"].append(account)
    result = identity.compile_contract(manifest, config)
    assert len(result["accounts"]) == 2
    assert not result["accounts"][account["name"]]["enabled"]


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("openbao", "authMount", "oidc"),
        ("openbao", "tokenTtl", True),
        ("identity", "jwtTtl", 0),
        ("identity", "url", "http://idp.example.test"),
        ("identity", "url", "https://idp.example.test/path"),
    ],
)
def test_catalog_is_strict(config, section, key, value):
    config[section][key] = value
    with pytest.raises(identity.ContractError):
        identity.catalog(config)


def fake_tofu(calls):
    def invoke(directory, *arguments, **kwargs):
        calls.append(arguments)
        if arguments[0] == "plan":
            (directory / "identity.tfplan").write_bytes(b"encrypted-plan-placeholder")
        if arguments[0] == "show":
            return json.dumps(
                {
                    "resource_changes": [
                        {
                            "address": "module.identity.authentik_user.service",
                            "change": {
                                "actions": ["create"],
                                "after": {"do_not_print": "private"},
                            },
                        }
                    ]
                }
            ).encode()
        if arguments[0] == "output":
            return b"{}"
        return b""

    return invoke


def test_apply_requires_exact_saved_plan(
    config, manifest, tmp_path, monkeypatch, capsys
):
    calls = []
    monkeypatch.setattr(identity, "tofu", fake_tofu(calls))
    contract = identity.compile_contract(manifest, config)
    identity.execute("plan", config, contract, tmp_path, "application")
    assert "do_not_print" not in capsys.readouterr().out
    changed = copy.deepcopy(contract)
    changed["accounts"]["svc-inventory-dev"]["enabled"] = False
    with pytest.raises(identity.ContractError):
        identity.execute("apply", config, changed, tmp_path, "application")
    assert not any(c[0] == "apply" for c in calls)
    identity.execute("apply", config, contract, tmp_path, "application")
    assert sum(c[0] == "plan" for c in calls) == 1
    assert sum(c[0] == "apply" for c in calls) == 1
    with pytest.raises(identity.ContractError):
        identity.execute("apply", config, contract, tmp_path, "application")
    artifacts = list(tmp_path.rglob("deployment.json"))
    assert len(artifacts) == 1 and artifacts[0].stat().st_mode & 0o777 == 0o600


def test_failed_apply_can_retry_saved_plan(config, manifest, tmp_path, monkeypatch):
    calls = []
    real = fake_tofu(calls)
    monkeypatch.setattr(identity, "tofu", real)
    contract = identity.compile_contract(manifest, config)
    identity.execute("plan", config, contract, tmp_path, "application")

    def fail(directory, *args, **kwargs):
        if args[0] == "apply":
            raise identity.ContractError("provider failure")
        return real(directory, *args, **kwargs)

    monkeypatch.setattr(identity, "tofu", fail)
    with pytest.raises(identity.ContractError):
        identity.execute("apply", config, contract, tmp_path, "application")
    assert list(tmp_path.rglob("identity.tfplan"))
    monkeypatch.setattr(identity, "tofu", real)
    identity.execute("apply", config, contract, tmp_path, "application")


def test_private_workspace_refuses_symlinks(tmp_path):
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(identity.ContractError):
        identity.private_directory(link / "state")


def test_provider_errors_and_debug_env_are_not_exposed(tmp_path, monkeypatch):
    captured = {}

    def run(*args, **kwargs):
        captured.update(kwargs)
        from subprocess import CompletedProcess

        return CompletedProcess(
            args[0], 1, b"sensitive provider output", b"sensitive error"
        )

    monkeypatch.setenv("TF_LOG", "TRACE")
    monkeypatch.setenv("TF_CLI_ARGS", "-debug")
    monkeypatch.setattr(identity.subprocess, "run", run)
    with pytest.raises(identity.ContractError, match="suppressed"):
        identity.tofu(tmp_path, "plan")
    assert "TF_LOG" not in captured["env"] and "TF_CLI_ARGS" not in captured["env"]
    assert os.environ["TF_LOG"] == "TRACE"


def test_account_cannot_overlap_another_registered_namespace(config, manifest):
    config["applications"]["inventory"]["dev-worker"] = copy.deepcopy(
        config["applications"]["inventory"]["dev"]
    )
    manifest["serviceAccounts"][0]["name"] = "svc-inventory-dev-worker"
    with pytest.raises(identity.ContractError, match="overlaps"):
        identity.compile_contract(manifest, config)


@pytest.mark.parametrize("policy", ["root", "default"])
def test_profile_cannot_add_reserved_bao_policies(config, policy):
    config["roles"]["application-service"]["policies"] = [policy]
    with pytest.raises(identity.ContractError, match="Reserved"):
        identity.catalog(config)

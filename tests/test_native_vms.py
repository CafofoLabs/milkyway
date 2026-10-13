"""Native maps authorize literal references and isolate every workload identity."""

import copy
import json
import sys
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import native_vms
from service_identity import catalog, compile_contract, load

ROOT = Path(__file__).resolve().parents[1]


def test_each_vm_receives_only_its_own_account_from_grouped_credentials():
    tasks = yaml.safe_load(
        (ROOT / "ansible/roles/default_linux_vm/tasks/main.yml").read_text()
    )
    task = next(
        task
        for task in tasks
        if task["name"] == "Deliver only this workload's machine identity"
    )
    engine = Environment()
    engine.filters["to_json"] = json.dumps
    artifact = json.loads(
        engine.from_string(task["ansible.builtin.copy"]["content"]).render(
            delivered={
                "connection": {"vault_url": "https://bao.example.test"},
                "accounts": {
                    "first": {"password": "synthetic-first"},
                    "second": {"password": "synthetic-second"},
                },
            },
            native_instance={"account": "first"},
        )
    )
    assert set(artifact["accounts"]) == {"first"}
    assert task["no_log"] is True


def instance():
    return {
        "version": 1,
        "name": "first",
        "template": "milkyway/hermes-agent",
        "environment": "prod",
        "vm": {
            "node": "mercury",
            "vm_id": 105,
            "vcpus": 4,
            "memory_mb": 8192,
            "disk_gb": 50,
        },
        "parameters": {"provider": "ollama-cloud", "model": "gpt-oss:120b"},
        "env": {"HERMES_TIMEZONE": "UTC"},
        "secret_env": {
            "OLLAMA_API_KEY": {
                "mount": "secret",
                "path": "apps/hermes/prod/first/ollama",
                "key": "api_key",
            }
        },
    }


def test_compilation_and_multiple_instance_account_preservation():
    first = native_vms.compile_map(instance(), ROOT)
    document = instance()
    document["name"] = "second"
    document["vm"]["vm_id"] = 106
    second = native_vms.compile_map(document, ROOT)
    manifest = native_vms.manifests([first, second])[("hermes", "prod")]
    assert [a["name"] for a in manifest["serviceAccounts"]] == [
        "svc-hermes-prod-first",
        "svc-hermes-prod-second",
    ]
    assert first["software"]["commit"] == "71d34bad1045610252eda02ee79549436896e784"
    assert first["parameters"]["browser"] is False


@pytest.mark.parametrize(
    "value",
    [
        "plaintext",
        {"mount": "secret", "path": "../platform", "key": "api_key"},
        {"mount": "secret", "path": "apps/*", "key": "api_key"},
        {
            "mount": "secret",
            "path": "apps/hermes",
            "key": "api_key",
            "fallback": "plaintext",
        },
    ],
)
def test_secret_values_and_ambiguous_paths_are_rejected(value):
    document = instance()
    document["secret_env"]["OLLAMA_API_KEY"] = value
    with pytest.raises(ValueError):
        native_vms.compile_map(document, ROOT)


@pytest.mark.parametrize("key", ["PATH", "LD_PRELOAD", "PYTHONPATH", "MILKYWAY_TOKEN"])
def test_process_configuration_cannot_be_overridden(key):
    document = instance()
    document["env"] = {key: "test"}
    with pytest.raises(ValueError):
        native_vms.compile_map(document, ROOT)


def test_plaintext_provider_keys_and_conflicting_bindings_are_rejected():
    document = instance()
    document["env"]["OLLAMA_API_KEY"] = "synthetic-only"
    with pytest.raises(ValueError):
        native_vms.compile_map(document, ROOT)


def test_dashboard_requires_explicit_https_origins():
    document = instance()
    document["parameters"]["dashboard"] = True
    with pytest.raises(ValueError, match="HTTPS"):
        native_vms.compile_map(document, ROOT)
    document["env"].update(
        HERMES_DASHBOARD_PUBLIC_URL="https://hermes.example.test",
        HERMES_DASHBOARD_OIDC_ISSUER="https://auth.example.test/application/o/hermes/",
    )
    assert native_vms.compile_map(document, ROOT)["parameters"]["dashboard"]
    for value in (
        "http://hermes.example.test",
        "https://user:password@example.test",
        "https://hermes.example.test?x=1",
        "https://hermes.example.test/other",
    ):
        document["env"]["HERMES_DASHBOARD_PUBLIC_URL"] = value
        with pytest.raises(ValueError):
            native_vms.compile_map(document, ROOT)


@pytest.mark.parametrize("enabled", [False, True])
def test_dashboard_configuration_does_not_require_oidc_values_when_disabled(enabled):
    document = instance()
    document["parameters"]["dashboard"] = enabled
    if enabled:
        document["env"].update(
            HERMES_DASHBOARD_PUBLIC_URL="https://hermes.example.test",
            HERMES_DASHBOARD_OIDC_ISSUER="https://auth.example.test/application/o/hermes/",
        )
    tasks = yaml.safe_load(
        (ROOT / "ansible/roles/hermes_agent/tasks/main.yml").read_text()
    )
    content = next(
        t["ansible.builtin.copy"]["content"]
        for t in tasks
        if t["name"] == "Configure the native agent"
    )
    engine = Environment()
    engine.filters.update(
        bool=bool,
        ternary=lambda condition, yes, no: yes if condition else no,
        combine=lambda a, b: a | b,
        to_nice_yaml=yaml.safe_dump,
    )
    variables = {"native_instance": native_vms.compile_map(document, ROOT)}
    if enabled:
        variables.update(
            native_dashboard_client_id="a" * 32,
            native_dashboard_proxy_address="100.64.0.1",
        )
    configuration = yaml.safe_load(engine.from_string(content).render(**variables))
    assert ("dashboard" in configuration) == enabled
    if enabled:
        assert configuration["dashboard"]["oauth"]["provider"] == "self-hosted"
        assert configuration["dashboard"]["trusted_proxies"] == ["100.64.0.1"]


def test_bindings_never_grant_their_own_authorization():
    configuration = load(ROOT / "examples/service-accounts/catalog.yaml")
    configuration["applications"] = {
        "hermes": {
            "prod": {
                "roles": ["application-service"],
                "secrets": [{"mount": "secret", "path": "apps/hermes/prod/allowed"}],
            }
        }
    }
    configuration["roles"]["application-service"] = {"policies": []}
    trusted = catalog(configuration)
    manifest = native_vms.manifests([native_vms.compile_map(instance(), ROOT)])[
        ("hermes", "prod")
    ]
    with pytest.raises(ValueError, match="not authorized"):
        compile_contract(manifest, trusted)


def test_duplicate_yaml_keys_fail_before_compilation(tmp_path):
    document = tmp_path / "bad.yaml"
    document.write_text("name: first\nname: second\n")
    with pytest.raises(ValueError, match="unique"):
        load(document)


@pytest.mark.parametrize(
    "field,value", [("vcpus", True), ("vm_id", 9000.1), ("memory_mb", 512)]
)
def test_invalid_sizes(field, value):
    document = copy.deepcopy(instance())
    document["vm"][field] = value
    with pytest.raises(ValueError):
        native_vms.compile_map(document, ROOT)


def test_authentik_yaml_preserves_visibility_metadata_and_provider_settings():
    settings = native_vms.authentik_configuration(
        {
            "name": "Research agent",
            "slug": "research",
            "group": "Agents",
            "description": "Private research dashboard",
            "publisher": "CafofoLabs",
            "icon_url": "https://static.example.test/hermes.png",
            "launch_url": "https://hermes.example.test/chat",
            "show_in_library": False,
            "open_in_new_tab": True,
            "policy_engine_mode": "all",
            "backchannel_providers": [12],
            "access_groups": ["platform_admins", "platform_users"],
            "provider": {
                "name": "Research OIDC",
                "sub_mode": "user_uuid",
                "access_token_validity": "minutes=15",
            },
        },
        "first",
        "https://hermes.example.test",
    )
    assert settings["slug"] == "research"
    assert settings["show_in_library"] is False
    assert settings["provider"]["client_type"] == "public"
    assert settings["provider"]["name"] == "Research OIDC"
    assert settings["provider"]["access_token_validity"] == "minutes=15"
    assert settings["backchannel_providers"] == [12]
    assert settings["policy_engine_mode"] == "all"


@pytest.mark.parametrize(
    "settings",
    [
        {"show_in_library": "false"},
        {"open_in_new_tab": 1},
        {"policy_engine_mode": "invalid"},
        {"access_groups": []},
        {"access_groups": ["platform_admins", "platform_admins"]},
        {"backchannel_providers": [True]},
        {"backchannel_providers": [1, 1]},
        {"launch_url": "https://user:password@example.test"},
        {"icon_url": "http://example.test/icon.png"},
        {"provider": {"client_secret": "synthetic"}},
        {"provider": {"client_type": "confidential"}},
        {"provider": {"grant_types": ["authorization_code", "implicit"]}},
        {"provider": {"sub_mode": "invalid"}},
        {"provider": {"access_token_validity": "seconds=0"}},
        {"provider": {"authorization_flow_slug": "../flow"}},
    ],
)
def test_authentik_configuration_rejects_ambiguous_or_incompatible_settings(settings):
    with pytest.raises(ValueError):
        native_vms.authentik_configuration(
            settings, "first", "https://hermes.example.test"
        )

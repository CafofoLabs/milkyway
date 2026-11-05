"""Native maps authorize literal references and isolate every workload identity."""

import base64
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
    assert first["software"]["commit"] == "b200f5bc60e31588ba2cb60e288029c4a54ba5fa"
    assert first["parameters"]["browser"] is False
    assert first["parameters"]["bot_desktop"] is False


def test_bot_desktop_is_explicit_and_boolean():
    document = instance()
    document["parameters"]["bot_desktop"] = True
    assert native_vms.compile_map(document, ROOT)["parameters"]["bot_desktop"] is True
    document["parameters"]["bot_desktop"] = "true"
    with pytest.raises(ValueError, match="bot_desktop must be boolean"):
        native_vms.compile_map(document, ROOT)


def test_bot_desktop_recipe_manages_private_screen_and_pinned_driver():
    tasks = yaml.safe_load(
        (ROOT / "ansible/roles/hermes_agent/tasks/main.yml").read_text()
    )
    named = {task["name"]: task for task in tasks}
    packages = named["Install the minimal private Bot Desktop stack"][
        "ansible.builtin.apt"
    ]
    assert packages["install_recommends"] is False
    assert {"tigervnc-standalone-server", "xfwm4", "xfce4-panel", "xauth"} <= set(
        packages["name"]
    )
    assert named["Install the pinned computer-use driver"]["ansible.builtin.command"][
        "argv"
    ][1:] == [
        "computer-use",
        "install",
    ]
    assert named["Start the private Bot Desktop screen"]["ansible.builtin.command"][
        "argv"
    ][1:] == [
        "computer-use",
        "screen",
        "start",
    ]
    status = named["Inspect the private Bot Desktop screen"]
    assert "hermes_bot_screen_status.rc == 1" in status["failed_when"]
    assert "'not running' in hermes_bot_screen_status.stdout" in status["failed_when"]


def test_anthropic_login_can_use_no_vault_secret():
    document = instance()
    document["parameters"] = {"provider": "anthropic", "model": "claude-sonnet-4-6"}
    document["secret_env"] = {}
    compiled = native_vms.compile_map(document, ROOT)
    assert compiled["secret_env"] == {}
    account = native_vms.manifests([compiled])[("hermes", "prod")]["serviceAccounts"][0]
    assert account["secrets"]["read"] == []


def test_unconfigured_provider_still_requires_a_secret():
    document = instance()
    document["secret_env"] = {}
    with pytest.raises(ValueError, match="provider credential"):
        native_vms.compile_map(document, ROOT)


@pytest.mark.parametrize("cpu_type", [None, "x86-64-v3", "host"])
def test_native_vm_cpu_type_is_preserved_with_compatible_default(cpu_type):
    document = instance()
    if cpu_type is not None:
        document["vm"]["cpu_type"] = cpu_type
    compiled = native_vms.compile_map(document, ROOT)
    assert compiled["vm"]["cpu_type"] == (cpu_type or "x86-64-v3")


@pytest.mark.parametrize("cpu_type", [None, "", True, [], "unsupported"])
def test_invalid_cpu_types_are_rejected(cpu_type):
    document = instance()
    document["vm"]["cpu_type"] = cpu_type
    with pytest.raises(ValueError, match="CPU type"):
        native_vms.compile_map(document, ROOT)


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
@pytest.mark.parametrize("bot_desktop", [False, True])
@pytest.mark.parametrize("webapp", [False, True])
def test_dashboard_configuration_does_not_require_oidc_values_when_disabled(
    enabled, bot_desktop, webapp
):
    if webapp and not enabled:
        return
    document = instance()
    document["parameters"]["dashboard"] = enabled
    document["parameters"]["webapp"] = webapp
    if webapp:
        document["env"]["HERMES_WEBAPP_PUBLIC_URL"] = "https://workspace.example.test"
    document["parameters"]["bot_desktop"] = bot_desktop
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
        combine=lambda a, b, **kwargs: (
            merge(a, b) if kwargs.get("recursive") else a | b
        ),
        b64decode=lambda value: base64.b64decode(value).decode(),
        from_yaml=yaml.safe_load,
        to_nice_yaml=yaml.safe_dump,
    )

    def merge(left, right):
        result = copy.deepcopy(left)
        for key, value in right.items():
            result[key] = (
                merge(result[key], value)
                if isinstance(value, dict) and isinstance(result.get(key), dict)
                else value
            )
        return result

    existing = {
        "custom": {"preserved": True},
        "model": {"temperature": 0.4},
        "dashboard": {"theme": "midnight"},
    }
    variables = {
        "native_instance": native_vms.compile_map(document, ROOT),
        "hermes_existing_config": {
            "content": base64.b64encode(yaml.safe_dump(existing).encode()).decode()
        },
    }

    if enabled:
        variables.update(
            native_dashboard_client_id="a" * 32,
            native_dashboard_proxy_address="100.64.0.1",
        )
    configuration = yaml.safe_load(engine.from_string(content).render(**variables))
    assert configuration["custom"] == existing["custom"]
    assert configuration["model"]["temperature"] == 0.4
    assert configuration["dashboard"]["theme"] == "midnight"
    assert configuration["webapp"]["enabled"] == webapp
    if webapp:
        assert configuration["webapp"]["public_url"] == "https://workspace.example.test"
        assert configuration["webapp"]["host"] == "0.0.0.0"
    assert ("bot_desktop" in configuration) == bot_desktop
    assert ("browser" in configuration) == bot_desktop
    if bot_desktop:
        assert configuration["bot_desktop"]["auto_start"] is True
        assert configuration["browser"]["headed"] is True
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


@pytest.mark.parametrize(
    "url",
    [
        "http://workspace.example.test",
        "https://workspace.example.test/path",
        "https://workspace.example.test?x=1",
        "https://workspace.example.test:444",
        "https://user:password@workspace.example.test",
    ],
)
def test_webapp_rejects_unsafe_origins(url):
    document = instance()
    document["parameters"].update(dashboard=True, webapp=True)
    document["env"]["HERMES_WEBAPP_PUBLIC_URL"] = url
    with pytest.raises(ValueError, match="Webapp"):
        native_vms.compile_map(document, ROOT)


def test_webapp_requires_managed_authentication():
    document = instance()
    document["parameters"]["webapp"] = True
    with pytest.raises(ValueError, match="OIDC"):
        native_vms.compile_map(document, ROOT)


def test_webapp_firewall_limits_remote_access_to_the_exact_proxy():
    template = (
        ROOT / "ansible/roles/host_firewall/templates/milkyway.nft.j2"
    ).read_text()
    engine = Environment()
    engine.filters["milkyway_ipv4_cidr"] = lambda value: value
    rendered = engine.from_string(template).render(
        ansible_managed="test",
        host_firewall_effective_cutover=True,
        native_instance={"parameters": {"webapp": True}},
        native_dashboard_proxy_address="100.64.0.1",
    )
    allow = rendered.index("ip saddr 100.64.0.1/32 tcp dport 9120 accept")
    deny = rendered.index("tcp dport 9120 drop")
    tailnet = rendered.index('iifname "tailscale0" accept')
    assert allow < deny < tailnet


def test_user_gateway_migration_uses_the_live_session_guard():
    tasks = yaml.safe_load(
        (ROOT / "ansible/roles/hermes_agent/tasks/main.yml").read_text()
    )
    names = [task["name"] for task in tasks]
    stop = next(
        task
        for task in tasks
        if task["name"]
        == "Stop the user gateway only when upstream permits stopping live sessions"
    )
    assert stop["ansible.builtin.command"]["argv"][1:] == ["gateway", "stop"]
    assert stop["no_log"] is True
    assert names.index(stop["name"]) < names.index(
        "Disable duplicate user gateway supervision"
    )


@pytest.mark.parametrize(
    "work,socket_exists,allowed",
    [
        ({"active_agents": 0, "active_work": []}, True, True),
        ({"active_agents": 1, "active_work": []}, True, False),
        ({"active_agents": 0, "active_work": [{}]}, True, False),
        (None, True, False),
        (None, False, True),
    ],
)
def test_restart_handler_checks_live_work_at_the_restart_boundary(
    monkeypatch, work, socket_exists, allowed
):
    from types import SimpleNamespace

    handlers = yaml.safe_load(
        (ROOT / "ansible/roles/hermes_agent/handlers/main.yml").read_text()
    )
    assert "ansible.builtin.include_tasks" in handlers[0]
    tasks = yaml.safe_load(
        (ROOT / "ansible/roles/hermes_agent/tasks/restart_gateway.yml").read_text()
    )
    assert tasks[1]["ansible.builtin.systemd_service"]["name"] == "hermes-agent"
    code = tasks[0]["ansible.builtin.command"]["argv"][-1]
    monkeypatch.setattr(Path, "exists", lambda _: socket_exists)
    monkeypatch.setattr(sys, "path", sys.path[:])
    monkeypatch.setitem(
        sys.modules,
        "gateway.control_socket",
        SimpleNamespace(query_gateway_control=lambda *_: work),
    )
    if allowed:
        exec(code, {})  # noqa: S102 -- exercise the repository-owned Ansible probe
    else:
        with pytest.raises(AssertionError):
            exec(code, {})  # noqa: S102 -- exercise the repository-owned Ansible probe

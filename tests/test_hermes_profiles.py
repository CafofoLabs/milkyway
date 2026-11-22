"""Profile merges keep unmanaged Hermes settings and converge on repeated runs."""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ansible/roles/hermes_agent/filter_plugins"))
import hermes_profiles

TASKS = ROOT / "ansible/roles/hermes_agent/tasks/main.yml"


def existing():
    return {
        "custom": {"preserved": True},
        "model": {
            "provider": "old",
            "default": "old-model",
            "temperature": 0.4,
            "reasoning_effort": "high",
        },
        "agent": {"disabled_toolsets": ["browser"], "reasoning_effort": "low"},
        "delegation": {
            "max_iterations": 30,
            "provider": "old",
            "model": "old-delegate",
            "reasoning_effort": "low",
        },
        "auxiliary": {
            "vision": {"provider": "old", "model": "old-vision", "timeout": 30},
            "compression": {"provider": "auto", "model": ""},
        },
        "fallback_providers": [{"provider": "old", "model": "old-fallback"}],
        "approvals": {"mode": "manual", "deny": ["old pattern"]},
    }


def declared():
    return {
        "provider": "openrouter",
        "model": "example/model",
        "reasoning_effort": "xhigh",
        "delegation": {"model": "example/delegate"},
        "auxiliary": {"vision": {"provider": "openrouter", "model": "example/vision"}},
        "fallback": [{"provider": "ollama-cloud", "model": "gpt-oss:20b"}],
        "approvals_deny": ["rm -rf /", "mkfs"],
    }


def test_declared_profile_sets_managed_keys_and_keeps_the_rest():
    merged = hermes_profiles.hermes_profile(existing(), declared())
    assert merged["custom"] == {"preserved": True}
    assert merged["model"] == {
        "provider": "openrouter",
        "default": "example/model",
        "temperature": 0.4,
    }
    assert merged["agent"] == {
        "disabled_toolsets": ["browser"],
        "reasoning_effort": "xhigh",
    }
    assert merged["delegation"] == {
        "max_iterations": 30,
        "model": "example/delegate",
    }
    assert merged["auxiliary"] == {
        "vision": {"provider": "openrouter", "model": "example/vision", "timeout": 30},
        "compression": {"provider": "auto", "model": ""},
    }
    assert merged["fallback_providers"] == [
        {"provider": "ollama-cloud", "model": "gpt-oss:20b"}
    ]
    assert merged["approvals"] == {"mode": "manual", "deny": ["rm -rf /", "mkfs"]}


def test_undeclared_managed_keys_are_removed_but_approvals_kept():
    merged = hermes_profiles.hermes_profile(
        existing(), {"provider": "openrouter", "model": "example/model"}
    )
    assert "reasoning_effort" not in merged["model"]
    assert merged["agent"] == {"disabled_toolsets": ["browser"]}
    assert merged["delegation"] == {"max_iterations": 30}
    assert "fallback_providers" not in merged
    assert merged["auxiliary"] == existing()["auxiliary"]
    assert merged["approvals"] == existing()["approvals"]


def test_empty_configuration_gets_only_declared_sections():
    merged = hermes_profiles.hermes_profile(
        None, {"provider": "openrouter", "model": "example/model"}
    )
    assert merged == {"model": {"provider": "openrouter", "default": "example/model"}}


def test_missing_profile_declaration_leaves_configuration_unchanged():
    assert hermes_profiles.hermes_profile(existing(), None) == existing()


def test_input_is_not_mutated():
    original = existing()
    hermes_profiles.hermes_profile(original, declared())
    assert original == existing()


def test_repeated_merge_serializes_identically():
    def render(config):
        return yaml.safe_dump(
            hermes_profiles.hermes_profile(config, declared()), sort_keys=True
        )

    first = render(existing())
    assert render(yaml.safe_load(first)) == first


def test_filter_is_registered_for_ansible():
    filters = hermes_profiles.FilterModule().filters()
    assert filters["milkyway_hermes_profile"] is hermes_profiles.hermes_profile


def test_role_checks_profiles_before_writing_and_writes_privately():
    tasks = yaml.safe_load(TASKS.read_text())
    names = [task["name"] for task in tasks]
    guard = names.index(
        "Require declared Hermes profiles to exist before configuring them"
    )
    assert guard < names.index("Configure the native agent")
    assert "does not exist" in tasks[guard]["ansible.builtin.fail"]["msg"]
    default = tasks[names.index("Configure the native agent")]["ansible.builtin.copy"]
    assert "milkyway_hermes_profile" in default["content"]
    task = tasks[names.index("Configure declared Hermes profiles")]
    copy = task["ansible.builtin.copy"]
    assert copy["dest"].startswith("/var/lib/hermes/.hermes/profiles/")
    assert "to_nice_yaml" in copy["content"]
    assert (copy["owner"], copy["group"], copy["mode"]) == ("hermes", "hermes", "0600")
    assert copy["backup"] is True
    assert task["no_log"] is True
    assert task["notify"] == ["Restart native hermes", "Restart native dashboard"]
    slurp = tasks[names.index("Preserve profile settings outside the managed keys")]
    assert slurp["no_log"] is True
    # The default profile is written only by the existing configuration task.
    loop = tasks[names.index("Inspect declared Hermes profile directories")]["loop"]
    assert "rejectattr('key', 'equalto', 'default')" in loop

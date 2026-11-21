"""Merge a compiled MilkyWay profile declaration into a Hermes config.yaml mapping.

Pure function: it never reads or writes files. Unmanaged keys are preserved; managed
keys follow the declaration exactly, so repeating the merge with the same input is a
no-op and declarations removed from the map are removed from the configuration.
"""

import copy

DELEGATION_KEYS = ("provider", "model", "reasoning_effort")


def _section(config, key):
    value = config.get(key)
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _store(config, key, section, existed):
    # Avoid introducing an empty mapping for a section the file never had.
    if section or existed:
        config[key] = section


def hermes_profile(config, profile):
    """Return ``config`` with the managed keys of ``profile`` applied.

    ``profile`` is ``None`` when the map declares no such profile; the configuration
    is then returned unchanged so maps without ``profiles`` keep their behaviour.
    """
    if config is None:
        config = {}
    if profile is None:
        return config
    if not isinstance(config, dict) or not isinstance(profile, dict):
        raise TypeError("Hermes configuration and profile must be mappings")
    result = copy.deepcopy(config)

    model = _section(result, "model")
    model["provider"] = profile["provider"]
    model["default"] = profile["model"]
    # Hermes reads only agent.reasoning_effort; a model-level value is misleading.
    model.pop("reasoning_effort", None)
    result["model"] = model

    agent = _section(result, "agent")
    if "reasoning_effort" in profile:
        agent["reasoning_effort"] = profile["reasoning_effort"]
    else:
        agent.pop("reasoning_effort", None)
    _store(result, "agent", agent, "agent" in result)

    delegation = _section(result, "delegation")
    declared = profile.get("delegation", {})
    for key in DELEGATION_KEYS:
        if key in declared:
            delegation[key] = declared[key]
        else:
            delegation.pop(key, None)
    _store(result, "delegation", delegation, "delegation" in result)

    if profile.get("auxiliary"):
        auxiliary = _section(result, "auxiliary")
        for task, route in profile["auxiliary"].items():
            current = auxiliary.get(task)
            entry = copy.deepcopy(current) if isinstance(current, dict) else {}
            entry.update(provider=route["provider"], model=route["model"])
            auxiliary[task] = entry
        result["auxiliary"] = auxiliary

    if "fallback" in profile:
        result["fallback_providers"] = [
            {"provider": item["provider"], "model": item["model"]}
            for item in profile["fallback"]
        ]
    else:
        result.pop("fallback_providers", None)

    if "approvals_deny" in profile:
        approvals = _section(result, "approvals")
        approvals["deny"] = list(profile["approvals_deny"])
        result["approvals"] = approvals

    return result


class FilterModule:
    def filters(self):
        return {"milkyway_hermes_profile": hermes_profile}

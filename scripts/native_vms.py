"""Compile native VM maps and scoped identities without resolving secret values."""

import re
from pathlib import Path

from service_identity import catalog, compile_contract, fields, load, name, read_rule

ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*\Z")
RESERVED_ENV = {
    "PATH",
    "HOME",
    "USER",
    "SHELL",
    "PYTHONPATH",
    "PYTHONHOME",
    "HERMES_HOME",
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
}


def env_name(value):
    if (
        not isinstance(value, str)
        or not ENV_NAME.fullmatch(value)
        or value in RESERVED_ENV
        or value.startswith(("LD_", "DYLD_", "PYTHON", "MILKYWAY_"))
    ):
        raise ValueError("Unsupported environment variable name")
    return value


def secret_reference(value):
    fields(value, ("mount", "path", "key"))
    read_rule({"mount": value["mount"], "path": value["path"]})
    if not isinstance(value["key"], str) or not re.fullmatch(
        r"[A-Za-z0-9_-]+", value["key"]
    ):
        raise ValueError("Secret fields require literal names")
    return value


def compile_map(document, framework):
    fields(
        document,
        ("version", "name", "template", "environment", "vm"),
        ("env", "secret_env", "parameters", "credential_revision"),
    )
    if document["version"] != 1:
        raise ValueError("Unsupported native VM contract version")
    instance = name(document["name"])
    environment = name(document["environment"])
    reference = document["template"]
    if not isinstance(reference, str) or not reference.startswith("milkyway/"):
        raise ValueError("Select an explicit MilkyWay native template")
    template_name = name(reference.removeprefix("milkyway/"))
    if template_name != "hermes-agent":
        raise ValueError("The initial native application recipe supports Hermes only")
    directory = Path(framework) / "app-templates" / template_name
    if directory.is_symlink() or (directory / "template.yaml").is_symlink():
        raise ValueError("Template symlinks are forbidden")
    template = load(directory / "template.yaml")
    fields(
        template,
        (
            "version",
            "name",
            "runtime",
            "base",
            "application",
            "user",
            "release",
            "commit",
            "installer_sha256",
        ),
    )
    if (
        template["version"] != 1
        or template["name"] != template_name
        or template["runtime"] != "systemd"
        or template["base"] != "milkyway/default-linux-vm"
    ):
        raise ValueError("Unsupported native template composition")
    base_path = Path(framework) / "vm-templates/default-linux-vm/template.yaml"
    base = load(base_path)
    if (
        base
        != {
            "version": 1,
            "name": "default-linux-vm",
            "os": "debian-13",
            "runtime": "systemd",
        }
        or base_path.is_symlink()
    ):
        raise ValueError("Unsupported Linux VM base")
    for key in ("application", "user"):
        name(template[key])
    if template["user"] == "root" or len(template["user"]) > 31:
        raise ValueError("Workload users must be unprivileged Linux account names")
    if (
        not re.fullmatch(r"v\d+\.\d+\.\d+", template["release"])
        or not re.fullmatch(r"[a-f0-9]{40}", template["commit"])
        or not re.fullmatch(r"[a-f0-9]{64}", template["installer_sha256"])
    ):
        raise ValueError("Native software requires an immutable verified pin")
    vm = fields(document["vm"], ("node", "vm_id", "vcpus", "memory_mb", "disk_gb"))
    name(vm["node"])
    for key, low, high in (
        ("vm_id", 100, 999999999),
        ("vcpus", 1, 64),
        ("memory_mb", 1024, 65536),
        ("disk_gb", 8, 2048),
    ):
        if type(vm[key]) is not int or not low <= vm[key] <= high:
            raise ValueError("Invalid native VM sizing or identity")
    env = document.get("env", {})
    secrets = document.get("secret_env", {})
    if not isinstance(env, dict) or not isinstance(secrets, dict):
        raise TypeError("Environment bindings must be mappings")
    fields(env, (), env.keys())
    fields(secrets, (), secrets.keys())
    # Arbitrary values are accepted only in env; bindings can never be plaintext.
    for key, value in env.items():
        env_name(key)
        if (
            not isinstance(value, str)
            or "\x00" in value
            or key.endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD"))
        ):
            raise ValueError("Credentials must use secret_env references")
    for key, value in secrets.items():
        env_name(key)
        secret_reference(value)
    if env.keys() & secrets.keys():
        raise ValueError("An environment name cannot have two sources")
    parameters = fields(
        document.get("parameters", {}), (), ("provider", "model", "browser")
    )
    if not isinstance(parameters.get("provider"), str) or not re.fullmatch(
        r"[a-z][a-z0-9_-]*", parameters["provider"]
    ):
        raise ValueError("Select a model provider")
    if (
        not isinstance(parameters.get("model"), str)
        or not parameters["model"].strip()
        or any(ord(c) < 32 for c in parameters["model"])
    ):
        raise ValueError("Select an explicit model")
    if type(parameters.get("browser", False)) is not bool:
        raise ValueError("browser must be boolean")
    if not secrets:
        raise ValueError("Declare the required provider credential references")
    required_key = {
        "ollama-cloud": "OLLAMA_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }.get(parameters["provider"])
    if required_key and required_key not in secrets:
        raise ValueError("The selected provider requires its API key binding")
    revision = document.get("credential_revision", 1)
    if type(revision) is not int or revision < 1:
        raise ValueError("credential_revision must be positive")
    return {
        **document,
        "env": env,
        "secret_env": secrets,
        "parameters": {"browser": False, **parameters},
        "credential_revision": revision,
        "application": template["application"],
        "account": f"svc-{template['application']}-{environment}-{instance}",
        "software": template,
    }


def manifests(instances):
    grouped = {}
    for instance in instances:
        key = (instance["application"], instance["environment"])
        manifest = grouped.setdefault(
            key,
            {
                "version": 1,
                "application": key[0],
                "environment": key[1],
                "serviceAccounts": [],
            },
        )
        reads = {(v["mount"], v["path"]) for v in instance["secret_env"].values()}
        manifest["serviceAccounts"].append(
            {
                "name": instance["account"],
                "roles": ["application-service"],
                "credentialRevision": instance["credential_revision"],
                "secrets": {
                    "read": [
                        {"mount": mount, "path": path} for mount, path in sorted(reads)
                    ]
                },
            }
        )
    return grouped


def discover(directory, framework, catalog_path):
    instances = [
        compile_map(load(path), framework)
        for path in sorted(Path(directory).glob("*.yaml"))
    ]
    if len({i["name"] for i in instances}) != len(instances) or len(
        {i["vm"]["vm_id"] for i in instances}
    ) != len(instances):
        raise ValueError("Native VM names and IDs must be unique")
    trusted = catalog(load(catalog_path))
    for manifest in manifests(instances).values():
        compile_contract(manifest, trusted)
    return instances

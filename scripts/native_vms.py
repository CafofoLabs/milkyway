"""Compile native VM maps and scoped identities without resolving secret values."""

import re
from pathlib import Path
from urllib.parse import urlsplit

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


def authentik_configuration(value, instance, url):
    """Normalize application metadata while preserving Hermes' native OIDC contract."""
    defaults = {
        "name": "Hermes " + instance.title(),
        "slug": "hermes-" + instance,
        "group": "Infrastructure",
        "description": "",
        "publisher": "",
        "icon_url": "",
        "launch_url": url,
        "show_in_library": True,
        "open_in_new_tab": False,
        "policy_engine_mode": "any",
        "backchannel_providers": [],
        "access_groups": ["platform_admins"],
        "provider": {},
    }
    application = defaults | fields(value, (), defaults.keys())
    for key in (
        "name",
        "slug",
        "group",
        "description",
        "publisher",
        "icon_url",
        "launch_url",
    ):
        if not isinstance(application[key], str) or any(
            ord(c) < 32 for c in application[key]
        ):
            raise ValueError("Authentik application metadata must be literal text")
    if not application["name"].strip():
        raise ValueError("Authentik application name must not be empty")
    name(application["slug"])
    for key in ("show_in_library", "open_in_new_tab"):
        if type(application[key]) is not bool:
            raise ValueError("Authentik visibility and tab options must be boolean")
    if application["policy_engine_mode"] not in ("any", "all"):
        raise ValueError("Authentik policy_engine_mode must be any or all")
    for key in ("launch_url", "icon_url"):
        if key == "icon_url" and not application[key]:
            continue
        parsed = urlsplit(application[key])
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or any(c.isspace() or c in '"<>\\' for c in application[key])
        ):
            raise ValueError("Authentik links require credential-free HTTPS URLs")
    backchannels = application["backchannel_providers"]
    if (
        not isinstance(backchannels, list)
        or any(type(i) is not int or i <= 0 for i in backchannels)
        or len(set(backchannels)) != len(backchannels)
    ):
        raise ValueError("Backchannel providers require unique existing positive IDs")
    groups = application["access_groups"]
    if not isinstance(groups, list) or not groups:
        raise ValueError("Native dashboard access_groups must be explicit and nonempty")
    for group in groups:
        if not isinstance(group, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", group):
            raise ValueError(
                "Access groups must reference declared platform group keys"
            )
    if len(set(groups)) != len(groups):
        raise ValueError("Authentik access_groups must be unique")
    provider_defaults = {
        "name": application["name"],
        "client_type": "public",
        "sub_mode": "hashed_user_id",
        "grant_types": ["authorization_code", "refresh_token"],
        "access_token_validity": "hours=1",
        "refresh_token_validity": "days=30",
        "refresh_token_threshold": "seconds=0",
        "authorization_flow_slug": None,
        "invalidation_flow_slug": None,
        "signing_key_name": None,
        "scope_mappings": [],
    }
    provider = provider_defaults | fields(
        application["provider"], (), provider_defaults.keys()
    )
    if (
        not isinstance(provider["name"], str)
        or not provider["name"].strip()
        or any(ord(c) < 32 for c in provider["name"])
    ):
        raise ValueError("Authentik provider name must be literal nonempty text")
    if provider["client_type"] != "public":
        raise ValueError("Hermes requires a public OIDC client with PKCE")
    if provider["sub_mode"] not in (
        "hashed_user_id",
        "user_id",
        "user_uuid",
        "user_username",
        "user_email",
        "user_upn",
    ):
        raise ValueError("Unsupported Authentik subject mode")
    grants = provider["grant_types"]
    if (
        not isinstance(grants, list)
        or "authorization_code" not in grants
        or any(g not in ("authorization_code", "refresh_token") for g in grants)
        or len(set(grants)) != len(grants)
    ):
        raise ValueError(
            "Hermes OIDC requires authorization_code and optional refresh_token"
        )
    for key in (
        "access_token_validity",
        "refresh_token_validity",
        "refresh_token_threshold",
    ):
        if (
            not isinstance(provider[key], str)
            or not re.fullmatch(
                r"(?:days|hours|minutes|seconds)=\d+(?:;(?:days|hours|minutes|seconds)=\d+)*",
                provider[key],
            )
            or (
                key != "refresh_token_threshold"
                and not any(int(n) for n in re.findall(r"\d+", provider[key]))
            )
        ):
            raise ValueError(
                "Token validity requires positive durations and a nonnegative threshold"
            )
    mappings = provider["scope_mappings"]
    if (
        not isinstance(mappings, list)
        or any(
            not isinstance(mapping, str)
            or not re.fullmatch(
                r"goauthentik\.io/providers/oauth2/scope-[a-z0-9_-]+", mapping
            )
            for mapping in mappings
        )
        or len(set(mappings)) != len(mappings)
    ):
        raise ValueError(
            "Scope mappings must be unique Authentik managed OIDC scopes"
        )
    for key in ("authorization_flow_slug", "invalidation_flow_slug"):
        if provider[key] is not None:
            name(provider[key])
    signing = provider["signing_key_name"]
    if signing is not None and (
        not isinstance(signing, str)
        or not signing.strip()
        or any(ord(c) < 32 for c in signing)
    ):
        raise ValueError("Signing key must reference an existing named certificate")
    return application | {"provider": provider}


def compile_map(document, framework):
    fields(
        document,
        ("version", "name", "template", "environment", "vm"),
        ("env", "secret_env", "parameters", "credential_revision", "authentik"),
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
    vm = {"cpu_type": "x86-64-v3"} | fields(
        document["vm"],
        ("node", "vm_id", "vcpus", "memory_mb", "disk_gb"),
        ("cpu_type",),
    )
    if vm["cpu_type"] not in ("x86-64-v3", "host"):
        raise ValueError("Native VM CPU type must be x86-64-v3 or host")
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
        document.get("parameters", {}),
        (),
        ("provider", "model", "browser", "dashboard"),
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
    if type(parameters.get("dashboard", False)) is not bool:
        raise ValueError("dashboard must be boolean")
    if parameters.get("dashboard"):
        for key in ("HERMES_DASHBOARD_PUBLIC_URL", "HERMES_DASHBOARD_OIDC_ISSUER"):
            value = env.get(key, "")
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or any(c.isspace() or c in '"<>\\' for c in value)
            ):
                raise ValueError(
                    "Dashboard access requires explicit trusted HTTPS origins"
                )
        if urlsplit(env["HERMES_DASHBOARD_PUBLIC_URL"]).path not in ("", "/"):
            raise ValueError("The native dashboard must use a dedicated hostname")
        scopes = env.get(
            "HERMES_DASHBOARD_OIDC_SCOPES", "openid profile email"
        ).split()
        if (
            not scopes
            or "openid" not in scopes
            or any(
                not re.fullmatch(r"[a-z][a-z0-9_-]*", scope) for scope in scopes
            )
            or len(set(scopes)) != len(scopes)
        ):
            raise ValueError(
                "Dashboard OIDC scopes must be unique names and include openid"
            )
    authentik = None
    if parameters.get("dashboard") or "authentik" in document:
        authentik = authentik_configuration(
            document.get("authentik", {}),
            instance,
            env.get("HERMES_DASHBOARD_PUBLIC_URL", ""),
        )
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
        "vm": vm,
        "env": env,
        "secret_env": secrets,
        "parameters": {"browser": False, "dashboard": False, **parameters},
        "credential_revision": revision,
        "authentik": authentik,
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

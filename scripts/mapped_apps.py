"""Validate instance maps and render shared or consumer-local application templates."""

import json
import re
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

NAME = r"[a-z][a-z0-9-]{0,47}"
TAILSCALE_IMAGE = "tailscale/tailscale:stable@sha256:c507f3a2a6ab1cabd8d809b98edeb41edbd5c3fb6ad9632ffd098b4c7d0b4065"
LOGGING = {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}


class UniqueLoader(yaml.SafeLoader):
    """Reject duplicate declarations rather than silently accepting the last one."""


def unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValueError(f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping
)


def read_yaml(path):
    if path.is_symlink():
        raise ValueError(f"Refusing a symlink: {path}")
    result = yaml.load(path.read_text(), Loader=UniqueLoader)
    if not isinstance(result, dict):
        raise TypeError(f"Expected a YAML mapping: {path}")
    return result


def only(mapping, keys, description):
    if not isinstance(mapping, dict) or set(mapping) - set(keys):
        raise ValueError(f"Unsupported {description} fields")


def identifier(value, description):
    if not isinstance(value, str) or not re.fullmatch(NAME, value):
        raise ValueError(f"Invalid {description}")
    return value


def file_in(directory, filename):
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise ValueError("Template files must be immediate children of their directory")
    path = directory / filename
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing or symlinked template file: {path}")
    return path


def parameters_for(supplied, definitions):
    only(supplied, definitions, "parameter")
    result = {}
    types = {"string": str, "boolean": bool, "integer": int, "array": list}
    for key, definition in definitions.items():
        only(
            definition,
            ("type", "default", "pattern", "item_pattern", "enum"),
            "parameter schema",
        )
        if key not in supplied and "default" not in definition:
            raise ValueError(f"Missing required parameter: {key}")
        value = supplied.get(key, definition.get("default"))
        if type(value) is not types.get(definition["type"]):
            raise ValueError(f"Invalid type for parameter: {key}")
        if "enum" in definition and value not in definition["enum"]:
            raise ValueError(f"Unsupported value for parameter: {key}")
        if "pattern" in definition and not re.fullmatch(definition["pattern"], value):
            raise ValueError(f"Invalid identifier parameter: {key}")
        if "item_pattern" in definition and any(
            not isinstance(item, str)
            or not re.fullmatch(definition["item_pattern"], item)
            for item in value
        ):
            raise ValueError(f"Invalid array parameter: {key}")
        result[key] = value
    return result


def render(request, framework, local_templates):
    only(
        request,
        (
            "version",
            "name",
            "template",
            "worker",
            "parameters",
            "tailscale",
            "local_port",
        ),
        "map",
    )
    if request.get("version") != 1:
        raise ValueError("Expected application map version 1")
    name = identifier(request.get("name"), "application name")
    worker = identifier(request.get("worker", "ganymede"), "worker name")
    reference = request.get("template", "")
    source, separator, template_name = reference.partition("/")
    if not separator or source not in {"milkyway", "local"}:
        raise ValueError(
            "Use an explicit milkyway/<template> or local/<template> reference"
        )
    identifier(template_name, "template name")
    directory = (
        framework / "app-templates" if source == "milkyway" else local_templates
    ) / template_name
    if directory.is_symlink() or directory.parent.is_symlink():
        raise ValueError("Refusing a symlinked template directory")
    template = read_yaml(file_in(directory, "template.yaml"))
    only(
        template,
        (
            "version",
            "name",
            "primary_service",
            "port",
            "parameters",
            "immutable_parameters",
            "hooks",
        ),
        "template",
    )
    if template.get("version") != 1 or template.get("name") != template_name:
        raise ValueError("Template identity does not match its reference")
    parameters = parameters_for(
        request.get("parameters", {}), template.get("parameters", {})
    )
    tailscale = request.get("tailscale", {})
    only(tailscale, ("hostname", "ephemeral"), "Tailscale")
    hostname = identifier(tailscale.get("hostname", name), "Tailscale hostname")
    ephemeral = tailscale.get("ephemeral", False)
    if type(ephemeral) is not bool:
        raise ValueError("Tailscale ephemeral must be a boolean")
    port = template["port"]
    local_port = request.get("local_port", port)
    if any(
        type(value) is not int or not 1 <= value <= 65535
        for value in (port, local_port)
    ):
        raise ValueError("Application ports must be integers from 1 to 65535")
    context = {"name": name, "worker": worker, "parameters": parameters}
    environment = Environment(undefined=StrictUndefined, autoescape=False)
    compose = yaml.load(
        environment.from_string(
            file_in(directory, "compose.yaml.j2").read_text()
        ).render(**context),
        Loader=UniqueLoader,
    )
    primary = template["primary_service"]
    services = compose["services"]
    if (
        "tailscale" in services
        or primary not in services
        or not services[primary].get("healthcheck")
    ):
        raise ValueError(
            "Reserve tailscale for the platform and supply a primary service healthcheck"
        )
    if (
        services[primary].get("ports")
        or services[primary].get("networks")
        or services[primary].get("network_mode")
    ):
        raise ValueError("The platform owns primary service networking")
    services[primary]["ports"] = [f"127.0.0.1:{local_port}:{port}"]
    services[primary]["networks"] = {"default": {}, "development": {"aliases": [name]}}
    secret_path = f"/etc/nimbus/secrets/{name}-tailscale-key"
    sidecar = {
        "image": TAILSCALE_IMAGE,
        "restart": "unless-stopped",
        "hostname": hostname,
        "environment": {
            "TS_AUTHKEY": "file:/run/secrets/tailscale_auth_key",
            "TS_AUTH_ONCE": "true",
            "TS_HOSTNAME": hostname,
            "TS_USERSPACE": "true",
            "TS_ACCEPT_DNS": "false",
            "TS_STATE_DIR": "/var/lib/tailscale",
            "TS_SERVE_CONFIG": "/etc/tailscale/serve.json",
        },
        "volumes": [
            {
                "type": "bind",
                "source": secret_path,
                "target": "/run/secrets/tailscale_auth_key",
                "read_only": True,
                "bind": {"create_host_path": False},
            },
            {
                "type": "bind",
                "source": f"/etc/komodo/stacks/{name}/tailscale",
                "target": "/etc/tailscale",
                "read_only": True,
                "bind": {"create_host_path": False},
            },
        ],
        "networks": {"default": {}},
        "depends_on": {primary: {"condition": "service_started"}},
        "healthcheck": {
            "test": [
                "CMD-SHELL",
                'tailscale status --json | grep -q \'"BackendState": "Running"\'',
            ],
            "interval": "10s",
            "timeout": "5s",
            "retries": 12,
            "start_period": "10s",
        },
    }
    volumes = compose.setdefault("volumes", {})
    if "tailscale_state" in volumes:
        raise ValueError("tailscale_state is reserved for the platform")
    if ephemeral:
        sidecar["tmpfs"] = ["/var/lib/tailscale:mode=0700"]
        sidecar["environment"]["TS_TAILSCALED_EXTRA_ARGS"] = "--state=mem:"
    else:
        volumes["tailscale_state"] = {}
        sidecar["volumes"].append("tailscale_state:/var/lib/tailscale")
    services["tailscale"] = sidecar
    for service in services.values():
        service["logging"] = LOGGING.copy()
        service.setdefault("labels", {}).update(
            {"io.milkyway.app": name, "io.milkyway.template": reference}
        )
    compose["name"] = name
    networks = compose.setdefault("networks", {})
    if "development" in networks:
        raise ValueError("development is reserved for the platform")
    networks.update({"default": {}, "development": {"name": "nimbus-dev"}})
    hooks = template.get("hooks", {})
    only(hooks, ("prepare", "configure", "verify", "verify_client"), "hook")
    files = {filename: str(file_in(directory, filename)) for filename in hooks.values()}
    return {
        **context,
        "template": reference,
        "primary_service": primary,
        "services": list(services),
        "port": port,
        "local_port": local_port,
        "tailscale": {"hostname": hostname, "ephemeral": ephemeral},
        "tailscale_secret": "platform/tailscale/ephemeral"
        if ephemeral
        else "platform/tailscale/auth_key",
        "tailscale_key_file": secret_path,
        "hooks": hooks,
        "immutable_parameters": template.get("immutable_parameters", []),
        "files": files,
        "compose": yaml.safe_dump(compose, sort_keys=False),
        "serve_config": json.dumps(
            {"TCP": {str(port): {"TCPForward": f"{primary}:{port}"}}}, indent=2
        )
        + "\n",
        "config": {
            "project_name": name,
            "files_on_host": True,
            "run_directory": f"/etc/komodo/stacks/{name}",
            "file_paths": ["compose.yaml"],
            "env_file_path": ".komodo.env",
            "additional_env_files": [],
            "auto_update": False,
            "destroy_before_deploy": False,
        },
    }


def discover(maps, framework, local_templates):
    """Validate the entire batch before the caller performs any remote mutation."""
    result, names, hostnames, ports = [], set(), set(), set()
    if maps.is_symlink():
        raise ValueError("Refusing a symlinked map directory")
    for path in sorted([*maps.glob("*.yaml"), *maps.glob("*.yml")]):
        app = render(read_yaml(path), framework, local_templates)
        binding = (app["worker"], app["local_port"])
        if (
            app["name"] in names
            or app["tailscale"]["hostname"] in hostnames
            or binding in ports
        ):
            raise ValueError(
                "Duplicate application name, Tailscale hostname or local port on a worker"
            )
        names.add(app["name"])
        hostnames.add(app["tailscale"]["hostname"])
        ports.add(binding)
        result.append(app)
    if not result:
        raise ValueError("No application maps found")
    return result

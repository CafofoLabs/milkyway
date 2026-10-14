"""Exercise template reuse, instance isolation and the batch validation boundary."""

import importlib.util
import json
import shutil
import socket
import struct
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mapped_apps as library

ROOT = Path(__file__).resolve().parents[1]


def request(name="example", **extra):
    return {"version": 1, "name": name, "template": "milkyway/postgres-18", **extra}


def test_two_instances_share_a_template_but_not_state(tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir()
    (maps / "first.yaml").write_text(yaml.safe_dump(request("first")))
    (maps / "second.yaml").write_text(
        yaml.safe_dump(request("second", local_port=5433))
    )
    apps = library.discover(maps, ROOT, tmp_path / "templates")
    first, second = [yaml.safe_load(app["compose"]) for app in apps]
    assert (
        first["services"]["postgres"]["image"]
        == second["services"]["postgres"]["image"]
    )
    assert first["name"] != second["name"]
    assert apps[0]["tailscale_key_file"] != apps[1]["tailscale_key_file"]
    assert apps[0]["worker"] == "ganymede"
    assert "network_mode" not in first["services"]["postgres"]
    assert "depends_on" not in first["services"]["postgres"]
    assert first["services"]["postgres"]["ports"] == ["127.0.0.1:5432:5432"]
    assert second["services"]["postgres"]["ports"] == ["127.0.0.1:5433:5432"]
    assert (
        json.loads(apps[0]["serve_config"])["TCP"]["5432"]["TCPForward"]
        == "postgres:5432"
    )
    assert "ports" not in first["services"]["tailscale"]
    assert "cap_add" not in first["services"]["tailscale"]


def test_ephemeral_enrollment_does_not_remove_database_persistence(tmp_path):
    app = library.render(request(tailscale={"ephemeral": True}), ROOT, tmp_path)
    compose = yaml.safe_load(app["compose"])
    assert app["tailscale_secret"] == "platform/tailscale/ephemeral"
    assert "tailscale_state" not in compose["volumes"]
    assert "postgres_data" in compose["volumes"]
    assert (
        compose["services"]["tailscale"]["environment"]["TS_TAILSCALED_EXTRA_ARGS"]
        == "--state=mem:"
    )
    for service in compose["services"].values():
        assert service["logging"]["driver"] == "json-file"
    assert "TS_AUTHKEY: file:/run/secrets/tailscale_auth_key" in app["compose"]


def test_local_template_has_the_same_contract(tmp_path):
    shutil.copytree(ROOT / "app-templates/postgres-18", tmp_path / "custom")
    descriptor = tmp_path / "custom/template.yaml"
    metadata = yaml.safe_load(descriptor.read_text())
    metadata["name"] = "custom"
    descriptor.write_text(yaml.safe_dump(metadata))
    app = library.render(
        request(template="local/custom", parameters={"user": "thiago"}), ROOT, tmp_path
    )
    assert app["template"] == "local/custom"
    assert "POSTGRES_USER: thiago" in app["compose"]


def mcp_request(name="mcp-human", **extra):
    return {
        "version": 1,
        "name": name,
        "template": "milkyway/fastmcp-proxy",
        "local_port": 8101,
        "config_ref": {
            "mount": "secret",
            "path": "apps/mcp/human/atlassian",
            "version": 1,
        },
        "identity": {
            "application": "mcp-human",
            "environment": "prod",
            "account": "svc-mcp-human-prod",
        },
        **extra,
    }


def test_mcp_bundle_is_not_resolved_and_tls_stays_tailnet_only(tmp_path):
    app = library.render(mcp_request(), ROOT, tmp_path)
    compose = yaml.safe_load(app["compose"])
    service = compose["services"]["proxy"]
    assert service["user"] == "10001:10001"
    assert service["read_only"] is True
    assert service["ports"] == ["127.0.0.1:8101:8000"]
    assert app["tailnet_port"] == 443
    assert app["config"]["run_build"] is True
    assert app["config"]["auto_pull"] is False
    serve = json.loads(app["serve_config"])
    assert serve["TCP"] == {"443": {"HTTPS": True}}
    assert serve["AllowFunnel"] == {"${TS_CERT_DOMAIN}:443": False}
    assert "service_identity_runtime.py" in app["files"]
    assert "api_key" not in app["compose"]
    subprocess.run(
        ["docker", "compose", "-f", "-", "config", "--quiet"],
        input=app["compose"],
        text=True,
        check=True,
    )


@pytest.mark.parametrize(
    "extra",
    [
        {
            "config_ref": {
                "mount": "secret",
                "path": "apps/mcp/human",
                "version": "latest",
            }
        },
        {"config_ref": {"mount": "secret", "path": "apps/mcp/human", "version": 0}},
        {"config_ref": {"mount": "secret", "path": "../escape", "version": 1}},
        {
            "identity": {
                "application": "mcp-human",
                "environment": "prod",
                "account": "svc-mcp-human-prod",
                "credential_revision": False,
            }
        },
        {
            "config_ref": {
                "mount": "secret",
                "path": "apps/mcp/human",
                "version": 1,
                "api_key": "synthetic",
            }
        },
    ],
)
def test_invalid_runtime_binding_fails_before_remote_mutation(extra, tmp_path):
    with pytest.raises(ValueError):
        library.render(mcp_request(**extra), ROOT, tmp_path)


def test_bundle_rotation_changes_compose_without_changing_image_or_identity(tmp_path):
    first = library.render(mcp_request(), ROOT, tmp_path)
    second = library.render(
        mcp_request(
            config_ref={
                "mount": "secret",
                "path": "apps/mcp/human/atlassian",
                "version": 2,
            }
        ),
        ROOT,
        tmp_path,
    )
    one, two = [
        yaml.safe_load(app["compose"])["services"]["proxy"] for app in (first, second)
    ]
    assert one["image"] == two["image"]
    assert one["environment"]["MCP_CONFIG_VERSION"] == "1"
    assert two["environment"]["MCP_CONFIG_VERSION"] == "2"
    assert one != two


def test_catalog_rejects_another_company_bundle(tmp_path):
    catalog = yaml.safe_load(
        (ROOT / "examples/service-accounts/catalog.yaml").read_text()
    )
    catalog["applications"] = {
        "mcp-human": {
            "prod": {
                "roles": ["application-service"],
                "secrets": [{"mount": "secret", "path": "apps/mcp/human/atlassian"}],
            }
        }
    }
    catalog_path = tmp_path / "catalog.yaml"
    catalog_path.write_text(yaml.safe_dump(catalog))
    app = library.render(mcp_request(), ROOT, tmp_path)
    library.authorize([app], catalog_path)
    app["runtime"]["config_ref"]["path"] = "apps/mcp/coates/atlassian"
    with pytest.raises(ValueError, match="not authorized"):
        library.authorize([app], catalog_path)


@pytest.mark.parametrize(
    "extra",
    [
        {"name": "../unsafe"},
        {"template": "postgres-18"},
        {"template": "milkyway/../../unsafe"},
        {"parameters": {"user": "bad;sql"}},
        {"parameters": {"extensions": ["pgcrypto;sql"]}},
        {"parameters": {"unknown": True}},
        {"tailscale": {"ephemeral": "false"}},
        {"local_port": True},
        {"logging": {"enabled": False}},
    ],
)
def test_invalid_maps_are_rejected(extra, tmp_path):
    with pytest.raises(ValueError):
        library.render(request(**extra), ROOT, tmp_path)


def test_batch_rejects_a_port_collision_and_duplicate_yaml_keys(tmp_path):
    (tmp_path / "first.yaml").write_text(yaml.safe_dump(request("first")))
    (tmp_path / "second.yaml").write_text(yaml.safe_dump(request("second")))
    with pytest.raises(ValueError, match="Duplicate application"):
        library.discover(tmp_path, ROOT, tmp_path / "templates")
    (tmp_path / "first.yaml").write_text("name: first\nname: second\n")
    with pytest.raises(ValueError, match="Duplicate YAML"):
        library.read_yaml(tmp_path / "first.yaml")


@pytest.mark.parametrize("ephemeral", [False, True])
def test_postgres_template_is_accepted_by_native_compose(ephemeral, tmp_path):
    app = library.render(request(tailscale={"ephemeral": ephemeral}), ROOT, tmp_path)
    subprocess.run(
        ["docker", "compose", "-f", "-", "config", "--quiet"],
        input=app["compose"],
        text=True,
        check=True,
    )


@pytest.mark.parametrize("scram", [True, False])
def test_client_check_requires_postgres_scram_instead_of_just_an_open_port(scram):
    spec = importlib.util.spec_from_file_location(
        "postgres_client_check", ROOT / "app-templates/postgres-18/verify_client.py"
    )
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()

        def serve():
            with listener.accept()[0] as connection:
                connection.recv(4096)
                payload = struct.pack("!I", 10 if scram else 0) + (
                    b"SCRAM-SHA-256\0\0" if scram else b""
                )
                connection.sendall(b"R" + struct.pack("!I", len(payload) + 4) + payload)

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            if scram:
                hook.verify("127.0.0.1", listener.getsockname()[1], "thiago")
            else:
                with pytest.raises(ValueError, match="SCRAM"):
                    hook.verify("127.0.0.1", listener.getsockname()[1], "thiago")
        finally:
            thread.join(timeout=5)

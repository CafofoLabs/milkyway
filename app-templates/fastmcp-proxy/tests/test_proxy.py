"""Use synthetic credentials and real MCP clients to exercise policy boundaries."""

import importlib.util
import json
import sys
from pathlib import Path

import httpx2
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult
from mcp.shared.exceptions import MCPError
from mcp.types import TextContent

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "proxy_under_test", Path(__file__).resolve().parents[1] / "proxy.py"
)
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


def bundle(**extra):
    return {
        "hostname": "mcp-human",
        "upstream_url": "https://mcp.atlassian.com/v2/mcp",
        "auth_type": "basic",
        "email": "test@example.test",
        "api_key": "synthetic-upstream-key",
        "clients": {"hermes": "a" * 48},
        "allowed_tools": ["get_issue"],
        "cloud_id": "human",
        **extra,
    }


@pytest.mark.parametrize(
    "extra",
    [
        {"upstream_url": "http://remote.example/mcp"},
        {"upstream_url": "https://user:password@remote.example/mcp"},
        {"upstream_url": "https://127.0.0.1/mcp"},
        {"upstream_url": "https://remote.example/mcp?key=secret"},
        {"auth_type": "oauth"},
        {"api_key": "bad\r\nHeader: value"},
        {"hostname": "mcp-coates"},
        {"clients": {}},
        {"clients": {"hermes": "short"}},
        {"clients": {"first": "a" * 48, "second": "a" * 48}},
        {"allowed_tools": []},
        {"cloud_id": None},
        {"unexpected": "secret"},
        {"allowed_origins": ["*"]},
    ],
)
def test_invalid_bundle_fails_without_disclosing_values(extra):
    with pytest.raises(proxy.ConfigurationError) as error:
        proxy.validate_config(bundle(**extra), "mcp-human")
    assert "synthetic-upstream-key" not in str(error.value)


@pytest.mark.parametrize(
    "auth_type,values,header",
    [
        ("basic", {"email": "test@example.test", "api_key": "synthetic"}, "Basic "),
        ("bearer", {"api_key": "synthetic"}, "Bearer synthetic"),
        ("headers", {"headers": {"X-Api-Key": "synthetic"}}, None),
        ("none", {}, None),
    ],
)
def test_remote_authentication_modes(auth_type, values, header):
    data = bundle(auth_type=auth_type)
    data.pop("email")
    data.pop("api_key")
    data.update(values)
    data["clients"] = json.dumps(data["clients"])
    data["allowed_tools"] = json.dumps(data["allowed_tools"])
    config = proxy.validate_config(data, "mcp-human")
    if header:
        assert config["headers"]["Authorization"].startswith(header)
    else:
        assert config["headers"] == values.get("headers", {})


@pytest.mark.asyncio
async def test_instance_tokens_are_independent():
    first = proxy.AgentTokens({"hermes": "a" * 48})
    second = proxy.AgentTokens({"hermes": "b" * 48})
    assert (await first.verify_token("a" * 48)).client_id == "hermes"
    assert await second.verify_token("a" * 48) is None
    assert await first.verify_token("invalid") is None
    assert await first.verify_token("é" * 48) is None


@pytest.mark.asyncio
async def test_proxy_lists_and_calls_only_allowed_tools_in_one_cloud(capsys):
    upstream = FastMCP("Synthetic upstream")
    calls = []

    @upstream.tool
    def get_issue(cloudId: str):
        calls.append(cloudId)
        return "synthetic issue"

    @upstream.tool
    def delete_issue(cloudId: str):
        pytest.fail("A denied tool reached the upstream")

    @upstream.resource("data://private")
    def private_resource():
        pytest.fail("Resources must remain unavailable")

    server = proxy.create_server(proxy.validate_config(bundle(), "mcp-human"), upstream)
    async with Client(server) as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools] == ["get_issue"]
        schema = tools[0].input_schema
        assert schema["properties"]["cloudId"]["const"] == "human"
        assert schema["properties"]["cloudId"]["enum"] == ["human"]
        assert (
            "synthetic issue"
            in (await client.call_tool("get_issue", {"cloudId": "human"}))
            .content[0]
            .text
        )
        for tool, arguments in [
            ("delete_issue", {"cloudId": "human"}),
            ("get_issue", {"cloudId": "coates"}),
            ("get_issue", {}),
        ]:
            with pytest.raises(ToolError):
                await client.call_tool(tool, arguments)
        with pytest.raises(MCPError):
            await client.read_resource("data://private")
    assert calls == ["human"]
    assert "synthetic-upstream-key" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_http_authentication_is_enforced_before_upstream_access():
    upstream = FastMCP("Synthetic upstream")

    @upstream.tool
    def get_issue(cloudId: str):
        return "synthetic issue"

    config = proxy.validate_config(bundle(), "mcp-human")
    server = proxy.create_server(config, upstream)
    app = server.http_app(
        stateless_http=True,
        host_origin_protection=True,
        allowed_hosts=["testserver"],
        allowed_origins=[],
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        message = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
        headers = {"Accept": "application/json, text/event-stream"}
        assert (
            await client.post("/mcp", json=message, headers=headers)
        ).status_code == 401
        assert (
            await client.post(
                "/mcp",
                json=message,
                headers={**headers, "Authorization": "Bearer wrong"},
            )
        ).status_code == 401
        response = await client.post(
            "/mcp",
            json=message,
            headers={**headers, "Authorization": "Bearer " + "a" * 48},
        )
        assert response.status_code == 200
        response = await client.post(
            "/mcp",
            json=message,
            headers={
                **headers,
                "Authorization": "Bearer " + "a" * 48,
                "Origin": "https://attacker.example.test",
            },
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_upstream_error_content_is_not_relayed():
    upstream = FastMCP("Synthetic upstream")

    @upstream.tool
    def get_issue(cloudId: str):
        return ToolResult(
            content=[TextContent(type="text", text="sensitive upstream error")],
            is_error=True,
        )

    server = proxy.create_server(proxy.validate_config(bundle(), "mcp-human"), upstream)
    async with Client(server) as client:
        with pytest.raises(ToolError) as error:
            await client.call_tool("get_issue", {"cloudId": "human"})
        assert "sensitive upstream error" not in str(error.value)


@pytest.mark.asyncio
async def test_http_proxy_never_forwards_client_credentials_or_headers():
    upstream = FastMCP("Synthetic upstream")

    @upstream.tool
    def get_issue(cloudId: str):
        return "synthetic issue"

    upstream_app = upstream.http_app(stateless_http=True, allowed_hosts=["upstream"])
    observed = []

    async def capture(request):
        observed.append(dict(request.headers))

    def factory(**kwargs):
        kwargs["follow_redirects"] = False
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=upstream_app),
            event_hooks={"request": [capture]},
            **kwargs,
        )

    transport = proxy.StreamableHttpTransport(
        "http://upstream/mcp",
        headers={"Authorization": "Bearer synthetic-upstream"},
        httpx_client_factory=factory,
    )
    server = proxy.create_server(
        proxy.validate_config(bundle(), "mcp-human"), transport
    )
    app = server.http_app(stateless_http=True, allowed_hosts=["gateway"])
    async with (
        upstream_app.router.lifespan_context(upstream_app),
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://gateway"
        ) as client,
    ):
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": "Bearer " + "a" * 48,
                "X-Client-Secret": "synthetic-front-only",
            },
        )
        assert response.status_code == 200
        assert "get_issue" in response.text
    assert observed
    assert all(
        headers.get("authorization") == "Bearer synthetic-upstream"
        for headers in observed
    )
    assert all("x-client-secret" not in headers for headers in observed)


@pytest.mark.asyncio
async def test_outbound_client_refuses_redirects_and_environment_proxies():
    async with proxy.upstream_http_client(follow_redirects=True) as client:
        assert client.follow_redirects is False
        assert client.trust_env is False


def test_pinned_bundle_is_read_and_its_token_always_revoked(tmp_path, monkeypatch):
    binding = tmp_path / "binding.json"
    binding.write_text(
        json.dumps(
            {
                "account": "svc-mcp-human-prod",
                "hostname": "mcp-human",
                "config_ref": {
                    "mount": "secret",
                    "path": "apps/mcp/human/atlassian",
                    "version": 2,
                },
            }
        )
    )
    monkeypatch.setattr(
        proxy,
        "protected_load",
        lambda _: {
            "connection": {"vault_url": "https://bao.example.test"},
            "accounts": {"svc-mcp-human-prod": {}},
        },
    )
    monkeypatch.setattr(
        proxy, "authenticate", lambda *_: {"client_token": "synthetic-bao-token"}
    )
    revoked = []
    monkeypatch.setattr(proxy, "request", lambda *args: revoked.append(args[0]))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return json.dumps(
                {"data": {"data": bundle(), "metadata": {"version": 2}}}
            ).encode()

    class Opener:
        def open(self, request, timeout):
            assert request.full_url.endswith(
                "/secret/data/apps/mcp/human/atlassian?version=2"
            )
            return Response()

    monkeypatch.setattr(proxy, "build_opener", lambda *_: Opener())
    assert proxy.load_config(binding, tmp_path / "identity.json")["cloud_id"] == "human"
    assert revoked == ["https://bao.example.test/v1/auth/token/revoke-self"]

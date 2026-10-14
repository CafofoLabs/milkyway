"""A scoped remote MCP proxy; configuration and credentials never reach logs."""

import argparse
import asyncio
import base64
import hmac
import ipaddress
import json
import logging
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, urlopen

import httpx2
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from fastmcp.server import create_proxy
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware
from fastmcp.server.providers.proxy import ProxyClient
from service_identity_runtime import NoRedirect, authenticate, protected_load, request
from starlette.responses import PlainTextResponse


class ConfigurationError(ValueError):
    """Errors intentionally contain no supplied values."""


def structured(value, expected):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise ConfigurationError("Invalid structured configuration") from None
    if not isinstance(value, expected):
        raise ConfigurationError("Invalid structured configuration type")
    return value


def text(value):
    if (
        not isinstance(value, str)
        or not value.strip()
        or any(c in value for c in "\r\n\x00")
    ):
        raise ConfigurationError("Invalid configuration text")
    return value


def validate_config(document, expected_hostname):
    required = {"hostname", "upstream_url", "auth_type", "clients", "allowed_tools"}
    if (
        not isinstance(document, dict)
        or not required <= document.keys()
        or document.keys()
        - required
        - {"email", "api_key", "headers", "cloud_id", "allowed_origins"}
    ):
        raise ConfigurationError("Invalid MCP configuration fields")
    if document["hostname"] != expected_hostname or not re.fullmatch(
        r"[a-z][a-z0-9-]{0,47}", expected_hostname
    ):
        raise ConfigurationError("Bundle hostname differs from the declared instance")
    url = urlsplit(text(document["upstream_url"]))
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.hostname in {"localhost", "localhost.localdomain"}
    ):
        raise ConfigurationError(
            "Upstream must be a fixed HTTPS URL without credentials"
        )
    try:
        ipaddress.ip_address(url.hostname)
    except ValueError:
        pass
    else:
        raise ConfigurationError("Use a DNS hostname for the upstream")
    clients = structured(document["clients"], dict)
    if (
        not clients
        or any(
            not isinstance(name, str)
            or not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", name)
            or len(text(token)) < 32
            for name, token in clients.items()
        )
        or len(set(clients.values())) != len(clients)
    ):
        raise ConfigurationError(
            "Clients require unique private tokens of at least 32 characters"
        )
    tools = structured(document["allowed_tools"], list)
    if (
        not tools
        or any(
            not isinstance(tool, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", tool)
            for tool in tools
        )
        or len(set(tools)) != len(tools)
    ):
        raise ConfigurationError("Declare a nonempty exact tool allowlist")
    headers = {}
    auth_type = document["auth_type"]
    supplied = set(document) & {"email", "api_key", "headers"}
    if auth_type == "basic" and supplied == {"email", "api_key"}:
        email, key = text(document["email"]), text(document["api_key"])
        if ":" in email or "@" not in email:
            raise ConfigurationError("Basic authentication requires an email")
        headers["Authorization"] = (
            "Basic " + base64.b64encode(f"{email}:{key}".encode()).decode()
        )
    elif auth_type == "bearer" and supplied == {"api_key"}:
        headers["Authorization"] = "Bearer " + text(document["api_key"])
    elif auth_type == "headers" and supplied == {"headers"}:
        headers = structured(document["headers"], dict)
        if not headers or any(
            not isinstance(key, str)
            or not re.fullmatch(r"[A-Za-z0-9-]+", key)
            or key.lower()
            in {
                "host",
                "cookie",
                "content-length",
                "connection",
                "mcp-session-id",
                "mcp-protocol-version",
            }
            for key in headers
        ):
            raise ConfigurationError("Invalid upstream authentication headers")
        headers = {key: text(value) for key, value in headers.items()}
    elif auth_type != "none" or supplied:
        raise ConfigurationError("Unsupported or conflicting upstream authentication")
    cloud_id = document.get("cloud_id")
    if cloud_id is not None:
        text(cloud_id)
    if url.hostname.rstrip(".") == "mcp.atlassian.com" and not cloud_id:
        raise ConfigurationError("Atlassian requires one pinned cloud ID")
    origins = structured(document.get("allowed_origins", []), list)
    for origin in origins:
        parsed = urlsplit(text(origin))
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ConfigurationError("Origins must be exact HTTPS origins")
    return {
        "hostname": expected_hostname,
        "upstream_url": document["upstream_url"],
        "headers": headers,
        "clients": clients,
        "allowed_tools": frozenset(tools),
        "cloud_id": cloud_id,
        "allowed_origins": origins,
    }


def load_config(
    runtime_path=Path("/run/config/runtime.json"),
    credentials_path=Path("/run/secrets/identity.json"),
):
    runtime = json.loads(runtime_path.read_text())
    deployment = protected_load(credentials_path)
    account = runtime["account"]
    if set(deployment["accounts"]) != {account}:
        raise ConfigurationError("Only this instance's identity may be mounted")
    reference = runtime["config_ref"]
    session = authenticate(deployment["connection"], deployment["accounts"][account])
    token = session["client_token"]
    try:
        url = (
            deployment["connection"]["vault_url"]
            + "/v1/"
            + quote(reference["mount"], safe="")
            + "/data/"
            + quote(reference["path"], safe="/")
            + "?version="
            + str(reference["version"])
        )
        with build_opener(NoRedirect()).open(
            Request(url, headers={"X-Vault-Token": token}), timeout=30
        ) as response:
            payload = json.load(response)["data"]
        if payload["metadata"]["version"] != reference["version"]:
            raise ConfigurationError("Bao returned an unexpected bundle version")
        return validate_config(payload["data"], runtime["hostname"])
    finally:
        request(
            deployment["connection"]["vault_url"] + "/v1/auth/token/revoke-self",
            {},
            token,
        )


class AgentTokens(TokenVerifier):
    def __init__(self, clients):
        super().__init__()
        self.clients = clients

    async def verify_token(self, token):
        for client, expected in self.clients.items():
            if hmac.compare_digest(token.encode(), expected.encode()):
                return AccessToken(
                    token=token, client_id=client, subject=client, scopes=["mcp"]
                )
        return None


class Policy(Middleware):
    def __init__(self, config):
        self.tools = config["allowed_tools"]
        self.cloud_id = config["cloud_id"]

    async def on_message(self, context, call_next):
        if context.method and context.method.startswith(
            ("resources/", "prompts/", "tasks/")
        ):
            raise ToolError("Operation is disabled")
        try:
            return await call_next(context)
        except ToolError:
            raise ToolError("MCP operation denied or unavailable") from None
        except Exception:  # noqa: BLE001 -- upstream exceptions can contain credentials
            raise ToolError("Upstream MCP operation unavailable") from None

    async def on_list_tools(self, context, call_next):
        tools = await call_next(context)
        allowed = []
        for tool in tools:
            if tool.name not in self.tools:
                continue
            if self.cloud_id:
                if "cloudId" not in tool.parameters.get("properties", {}):
                    continue
                schema = deepcopy(tool.parameters)
                schema["properties"]["cloudId"].update(
                    const=self.cloud_id, enum=[self.cloud_id], default=self.cloud_id
                )
                tool = tool.model_copy(update={"parameters": schema})
            allowed.append(tool)
        return allowed

    async def on_call_tool(self, context, call_next):
        tool = context.message.name
        if tool not in self.tools:
            raise ToolError("Tool is not allowed")
        if (
            self.cloud_id
            and (context.message.arguments or {}).get("cloudId") != self.cloud_id
        ):
            raise ToolError("Cloud ID is not allowed")
        access = get_access_token()
        client = access.client_id if access else "internal"
        outcome = "failed"
        try:
            result = await call_next(context)
            if result.is_error:
                raise ToolError("Upstream tool failed")
            outcome = "completed"
            return result
        finally:
            # No inputs, outputs, URLs, exception details or credentials in telemetry.
            print(
                json.dumps(
                    {
                        "event": "mcp_tool",
                        "client": client,
                        "tool": tool,
                        "outcome": outcome,
                    }
                ),
                flush=True,
            )


def upstream_http_client(**kwargs):
    kwargs["follow_redirects"] = False
    kwargs["trust_env"] = False
    return httpx2.AsyncClient(**kwargs)


def create_server(config, backend=None):
    if backend is None:
        backend = StreamableHttpTransport(
            config["upstream_url"],
            headers=config["headers"],
            httpx_client_factory=upstream_http_client,
        )
    client = ProxyClient(
        backend,
        mode="auto",
        forward_incoming_headers=False,
        roots=[],
        sampling_handler=None,
        elicitation_handler=None,
        log_handler=None,
        progress_handler=None,
    )
    server = create_proxy(
        client,
        name="MilkyWay MCP proxy",
        auth=AgentTokens(config["clients"]),
        mask_error_details=True,
        middleware=[Policy(config)],
    )

    @server.custom_route("/health", methods=["GET"])
    async def health(_request):
        return PlainTextResponse("ok")

    return server


async def verify(config):
    token = next(iter(config["clients"].values()))
    async with Client("http://127.0.0.1:8000/mcp", auth=token) as client:
        tools = await client.list_tools()
        if not tools or not {tool.name for tool in tools} <= config["allowed_tools"]:
            raise ConfigurationError(
                "Upstream tools are missing or exceed the allowlist"
            )
        try:
            await client.call_tool("__milkyway_denied_probe__", {})
        except ToolError:
            print("Forbidden tool denied")
        else:
            raise ConfigurationError("Forbidden tool was accepted")
    async with httpx2.AsyncClient(timeout=5) as client:
        response = await client.post(
            "http://127.0.0.1:8000/mcp",
            headers={
                "Authorization": "Bearer milkyway-invalid-probe",
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        if response.status_code != 401:
            raise ConfigurationError("Invalid client token was accepted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    # Libraries may include remote error bodies in diagnostics; retain only our audit events.
    logging.disable(logging.CRITICAL)
    try:
        if args.healthcheck:
            with urlopen("http://127.0.0.1:8000/health", timeout=3) as response:
                if response.status != 200 or response.read() != b"ok":
                    raise ConfigurationError("Unhealthy proxy")
            return
        config = load_config()
        if args.verify:
            asyncio.run(verify(config))
            print("MCP authentication, upstream discovery and tool denial verified")
            return
        server = create_server(config)
        server.run(
            transport="http",
            host="0.0.0.0",
            port=8000,
            show_banner=False,
            stateless_http=True,
            host_origin_protection=True,
            allowed_hosts=["127.0.0.1", "localhost", config["hostname"] + ".*.ts.net"],
            allowed_origins=config["allowed_origins"],
        )
    except Exception:  # noqa: BLE001 -- startup errors must never disclose bundle values
        parser.exit(
            1, "MCP startup or verification failed; sensitive diagnostics suppressed.\n"
        )


if __name__ == "__main__":
    main()

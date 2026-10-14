"""Check certificate validation and unauthenticated denial through tailnet TLS."""

import json
import os
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Proxy redirects are refused")


def verify(hostname):
    endpoint = "https://" + hostname.rstrip(".")
    opener = build_opener(NoRedirect())
    with opener.open(endpoint + "/health", timeout=15) as response:
        if response.status != 200 or response.read() != b"ok":
            raise ValueError("Tailnet TLS health check failed")
    message = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    try:
        with opener.open(
            Request(
                endpoint + "/mcp",
                data=json.dumps(message).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            ),
            timeout=15,
        ):
            raise ValueError("Unauthenticated tailnet access was accepted")
    except HTTPError as error:
        if error.code != 401:
            raise ValueError("Expected an authentication challenge") from None


if __name__ == "__main__":
    verify(os.environ["MAPPED_APP_TAILSCALE_DNS"])
    print("Tailnet TLS certificate, routing and unauthenticated denial verified")

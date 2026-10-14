"""Verify an authenticated upstream discovery without returning any secret."""

import subprocess

result = subprocess.run(
    ["docker", "compose", "exec", "-T", "proxy", "python", "/app/proxy.py", "--verify"],
    capture_output=True,
    text=True,
    check=False,
)
if result.returncode:
    raise SystemExit(
        "MCP authentication or upstream acceptance failed; diagnostics suppressed"
    )
print("MCP authentication, discovery and denial checks passed")

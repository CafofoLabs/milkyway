"""Manage subscription-free repositories and bootstrap updates through Proxmox."""

import argparse
import json
import os
import re
import shlex
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

ACTIONS = ("repositories-plan", "repositories-apply", "updates-plan", "updates-apply")


def run(*args, env=None):
    return subprocess.run(
        args, check=True, capture_output=True, text=True, env=env
    ).stdout.strip()


def api(node, method, endpoint, *options, env=None):
    output = run(
        "pvesh",
        method,
        f"/nodes/{node}/{endpoint}",
        *options,
        "--output-format",
        "json",
        env=env,
    )
    if method == "create" and endpoint == "apt/update":
        # Native CLI workers stream progress before their final JSON task ID.
        task = json.loads(output.splitlines()[-1])
        if (
            not isinstance(task, str)
            or not task.startswith(f"UPID:{node}:")
            or not re.fullmatch(r"UPID:[A-Za-z0-9:@_.-]+", task)
        ):
            raise ValueError("Expected the native refresh task identifier")
        return task
    return json.loads(output) if output else None


def repository_plan(data, ceph):
    if data.get("errors"):
        raise ValueError("Repository parser errors require review")
    disable = []
    for file in data["files"]:
        for index, repo in enumerate(file["repositories"]):
            if not repo["Enabled"]:
                continue
            for uri in repo["URIs"]:
                parsed = urlsplit(uri)
                if (
                    parsed.username
                    or parsed.password
                    or parsed.scheme not in {"http", "https"}
                    or parsed.hostname
                    not in {
                        "enterprise.proxmox.com",
                        "download.proxmox.com",
                        "deb.debian.org",
                        "security.debian.org",
                    }
                ):
                    raise ValueError("Unexpected active repository; review separately")
                if "/ceph-" in parsed.path and not parsed.path.endswith(
                    "/" + ceph.removesuffix("-no-subscription")
                ):
                    raise ValueError(
                        "A Ceph major-version transition requires a separate plan"
                    )
            if not set(repo["Suites"]) <= {
                "trixie",
                "trixie-updates",
                "trixie-security",
            }:
                raise ValueError("Unexpected distribution suite")
            components = repo.get("Components", [])
            if any(
                urlsplit(uri).hostname == "enterprise.proxmox.com"
                for uri in repo["URIs"]
            ) or any(value in {"pve-test", "test"} for value in components):
                disable.append({"path": file["path"], "index": index})
    standard = {item["handle"]: item.get("status") for item in data["standard-repos"]}
    desired = ["no-subscription", ceph]
    if any(handle not in standard for handle in desired):
        raise ValueError(
            "The installed Proxmox does not support the selected repository"
        )
    return {
        "disable": disable,
        "add": [handle for handle in desired if not standard[handle]],
    }


def simulation(text):
    changes = []
    for line in text.splitlines():
        if line.startswith("Remv "):
            raise ValueError("Package removals require a separate plan")
        if line.startswith("Inst "):
            match = re.match(r"Inst (\S+)(?: \[[^]]+\])? \((\S+)", line)
            if not match:
                raise ValueError("Unexpected upgrade simulation format")
            package, version = match.groups()
            if package in {"pve-manager", "proxmox-ve"} and not version.startswith(
                "9."
            ):
                raise ValueError(
                    "A Proxmox major-version transition requires a separate plan"
                )
            changes.append({"package": package, "version": version})
    return changes


def refresh(node, env):
    task = api(node, "create", "apt/update", env=env)
    for _ in range(150):
        state = api(node, "get", f"tasks/{task}/status")
        if state["status"] == "stopped":
            if state.get("exitstatus") != "OK":
                raise ValueError(
                    "Proxmox index refresh failed; inspect its task locally"
                )
            return
        time.sleep(2)
    raise TimeoutError("Proxmox index refresh did not finish")


def remote(action, node):
    if os.geteuid() != 0 or socket.gethostname() != node:
        raise ValueError("Root access and the expected hostname are required")
    if (
        not run("pveversion").startswith("pve-manager/9.")
        or Path("/etc/pve/corosync.conf").exists()
    ):
        raise ValueError("Bootstrap updates require a standalone Proxmox VE 9 node")
    resources = json.loads(
        run("pvesh", "get", "/cluster/resources", "--output-format", "json")
    )
    if any(item.get("type") in {"qemu", "lxc"} for item in resources):
        raise ValueError("Existing workloads require a maintenance plan")
    ceph_version = run("dpkg-query", "-W", "-f=${Version}", "ceph-common")
    family = {"19": "squid", "20": "tentacle"}.get(ceph_version.split(".")[0])
    if not family:
        raise ValueError("Unsupported Ceph client version")
    ceph = f"ceph-{family}-no-subscription"
    data = api(node, "get", "apt/repositories")
    plan = repository_plan(data, ceph)
    if action == "repositories-plan":
        return {"repositories": plan, "changed": bool(plan["disable"] or plan["add"])}
    if action == "repositories-apply":
        changed = bool(plan["disable"] or plan["add"])
        for item in plan["disable"]:
            data = api(node, "get", "apt/repositories")
            api(
                node,
                "create",
                "apt/repositories",
                "--path",
                item["path"],
                "--index",
                str(item["index"]),
                "--enabled",
                "0",
                "--digest",
                data["digest"],
            )
        for handle in plan["add"]:
            data = api(node, "get", "apt/repositories")
            api(
                node,
                "set",
                "apt/repositories",
                "--handle",
                handle,
                "--digest",
                data["digest"],
            )
        remaining = repository_plan(api(node, "get", "apt/repositories"), ceph)
        if remaining["disable"] or remaining["add"]:
            raise ValueError("Repository reconciliation did not converge")
        return {"changed": changed, "repositories": remaining}
    if plan["disable"] or plan["add"]:
        raise ValueError("Apply the repository plan before updating")
    if run("dpkg", "--audit") or run("apt-mark", "showhold"):
        raise ValueError("Broken or held packages require review")
    with tempfile.NamedTemporaryFile(mode="w", prefix="milkyway-apt-") as configuration:
        configuration.write(
            'APT::Update::Error-Mode "any";\nAPT::Get::Assume-Yes "true";\nAPT::Get::Remove "false";\nDpkg::Options { "--force-confdef"; "--force-confold"; };\n'
        )
        configuration.flush()
        env = {
            **os.environ,
            "APT_CONFIG": configuration.name,
            "DEBIAN_FRONTEND": "noninteractive",
            "LC_ALL": "C",
        }
        refresh(node, env)
        changes = simulation(run("apt-get", "--simulate", "dist-upgrade", env=env))
        if action == "updates-apply" and changes:
            log = Path("/var/log/milkyway-updates.log")
            descriptor = os.open(
                log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "w") as output:
                os.fchmod(output.fileno(), 0o600)
                subprocess.run(
                    ["pveupgrade"],
                    check=True,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    env=env,
                    timeout=14400,
                )
            # pveupgrade may return zero even when its underlying APT command fails.
            if (
                run("dpkg", "--audit")
                or simulation(run("apt-get", "--simulate", "dist-upgrade", env=env))
                or api(node, "get", "apt/update")
            ):
                raise ValueError(
                    "Post-upgrade verification failed; inspect the root-only host log"
                )
    return {
        "changed": bool(changes),
        "packages": changes,
        "applied": action == "updates-apply",
        "reboot_required": Path("/var/run/reboot-required").exists(),
        "version": run("pveversion"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--hostname")
    args = parser.parse_args()
    try:
        if args.remote:
            if not args.hostname or not re.fullmatch(
                r"[a-z0-9][a-z0-9-]{0,62}", args.hostname
            ):
                raise ValueError("Invalid expected hostname")
            print(json.dumps(remote(args.action, args.hostname)))
        else:
            from proxmox_preflight import host_config, ssh_args

            host = host_config(args.inventory)
            ssh = ssh_args(host)
            ssh[-1] = shlex.join(
                [
                    "python3",
                    "-",
                    args.action,
                    "--remote",
                    "--hostname",
                    host["expected_hostname"],
                ]
            )
            result = subprocess.run(
                ssh,
                input=Path(__file__).read_text(),
                check=True,
                capture_output=True,
                text=True,
                timeout=14700,
            )
            print(result.stdout.strip())
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        raise SystemExit(
            f"Proxmox maintenance failed ({type(exc).__name__}); inspect host prerequisites and native tasks without exposing credentials"
        ) from None


if __name__ == "__main__":
    main()

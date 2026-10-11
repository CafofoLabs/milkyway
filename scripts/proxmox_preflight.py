"""Collect a Proxmox installation handoff over authenticated, verified SSH."""

import argparse
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import tomllib
from pathlib import Path


COMMANDS = {
    "version": ["pveversion"],
    "kernel": ["uname", "-r"],
    "addresses": ["ip", "-j", "address", "show"],
    "routes": ["ip", "-j", "route", "show"],
    "disks": ["lsblk", "-J", "-b", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS"],
    "resources": ["pvesh", "get", "/cluster/resources", "--output-format", "json"],
    "time_synchronized": [
        "timedatectl",
        "show",
        "--property=NTPSynchronized",
        "--value",
    ],
}
JSON_FIELDS = {"addresses", "routes", "disks", "resources"}


def collect():
    facts = {
        "schema_version": 1,
        "hostname": socket.gethostname(),
        "cpu_count": os.cpu_count(),
        "cluster_configured": Path("/etc/pve/corosync.conf").exists(),
        "reboot_required": Path("/var/run/reboot-required").exists(),
        "errors": [],
    }
    # Read only the numeric memory total, never arbitrary host configuration.
    facts["memory_kib"] = next(
        int(line.split()[1])
        for line in Path("/proc/meminfo").read_text().splitlines()
        if line.startswith("MemTotal:")
    )
    for name, args in COMMANDS.items():
        try:
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=20, check=True
            )
            facts[name] = (
                json.loads(result.stdout)
                if name in JSON_FIELDS
                else result.stdout.strip()
            )
        except (subprocess.SubprocessError, OSError, ValueError):
            # Never echo arbitrary command output or configuration on failures.
            facts["errors"].append(name)
    return facts


def host_config(path):
    host = tomllib.loads(path.read_text())["host"]
    if set(host) != {"address", "username", "expected_hostname", "ssh_port"}:
        raise ValueError(
            "Inventory requires only address, username, expected_hostname, ssh_port"
        )
    address = host["address"]
    try:
        ipaddress.IPv4Address(address)
    except ipaddress.AddressValueError:
        if len(address) > 253 or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9.-]*", address
        ):
            raise ValueError(
                "address must be an IPv4 address or DNS hostname"
            ) from None
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", host["username"]):
        raise ValueError("Invalid SSH username")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", host["expected_hostname"]):
        raise ValueError("expected_hostname must be the short Proxmox node name")
    if type(host["ssh_port"]) is not int or not 1 <= host["ssh_port"] <= 65535:
        raise ValueError("Invalid SSH port")
    return host


def ssh_args(host):
    return [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ForwardAgent=no",
        "-o",
        "ClearAllForwardings=yes",
        "-p",
        str(host["ssh_port"]),
        f"{host['username']}@{host['address']}",
        "python3 - --collect",
    ]


def assess(facts, host):
    blockers = list(facts.get("errors", []))
    if facts.get("schema_version") != 1:
        blockers.append("Unsupported report schema")
    if facts.get("hostname") != host["expected_hostname"]:
        blockers.append("Observed node name differs from inventory")
    if not re.match(r"^pve-manager/9\.", facts.get("version", "")):
        blockers.append("The initial baseline requires Proxmox VE 9.x")
    if facts.get("cluster_configured") is not False:
        blockers.append("Existing cluster membership requires a separate plan")
    resources = facts.get("resources")
    if not isinstance(resources, list):
        blockers.append("Cannot verify existing workloads")
    elif any(item.get("type") in {"qemu", "lxc"} for item in resources):
        blockers.append("Existing workloads require an explicit preservation plan")
    return blockers


def save_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "w") as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(report, output, indent=2, sort_keys=True)
        output.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--report", type=Path, default=Path(".milkyway/preflight.json"))
    args = parser.parse_args()
    if args.collect:
        print(json.dumps(collect()))
        return
    if args.inventory is None:
        parser.error("--inventory is required")
    try:
        host = host_config(args.inventory)
        result = subprocess.run(
            ssh_args(host),
            input=Path(__file__).read_text(),
            capture_output=True,
            text=True,
            check=True,
            timeout=180,
        )
        facts = json.loads(result.stdout)
        blockers = assess(facts, host)
        save_report(args.report, {"facts": facts, "blockers": blockers})
        print(f"Read-only report saved to {args.report}; blockers: {len(blockers)}")
        if blockers:
            for item in blockers:
                print(f"- {item}")
            raise SystemExit(1)
        print(
            "Installation inventory collected. Baseline changes still require a reviewed plan."
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        print(
            f"Preflight failed ({type(exc).__name__}); verify inventory and trusted SSH access.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

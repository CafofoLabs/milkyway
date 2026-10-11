"""Plan or apply the hostname of an empty standalone Proxmox node over SSH."""

import argparse
import ipaddress
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
from pathlib import Path


def command(*args):
    return subprocess.run(
        args, check=True, capture_output=True, text=True
    ).stdout.strip()


def rewrite_hosts(text, previous, desired, address):
    lines = text.splitlines(keepends=True)
    matches = 0
    for index, line in enumerate(lines):
        body, separator, comment = line.partition("#")
        fields = body.split()
        if fields and fields[0] == address:
            if not any(
                name == previous or name.startswith(previous + ".")
                for name in fields[1:]
            ):
                if desired in fields[1:]:
                    matches += 1
                    continue
                raise ValueError("Management address does not map to the expected node")
            fields[1:] = [
                desired + name[len(previous) :]
                if name == previous or name.startswith(previous + ".")
                else name
                for name in fields[1:]
            ]
            lines[index] = (
                " ".join(fields)
                + (" #" + comment.rstrip("\n") if separator else "")
                + "\n"
            )
            matches += 1
    if matches != 1:
        raise ValueError("Require exactly one management address entry in /etc/hosts")
    return "".join(lines)


def validate_node(path):
    allowed = {
        "lxc",
        "qemu-server",
        "openvz",
        "priv",
        "pve-ssl.key",
        "pve-ssl.pem",
        "lrm_status",
        "ssh_known_hosts",
    }
    if path.exists():
        for entry in path.iterdir():
            if entry.is_symlink() or entry.name not in allowed:
                raise ValueError(
                    "Unexpected old-node configuration; preserve it for manual review"
                )
            if entry.is_dir() and any(entry.iterdir()):
                raise ValueError("Old-node configuration directories must be empty")


def remote(action, previous, desired, address):
    if os.geteuid() != 0:
        raise ValueError("The initial rename requires root")
    if Path("/etc/pve/corosync.conf").exists():
        raise ValueError("Cluster members cannot use this operation")
    if not command("pveversion").startswith("pve-manager/9."):
        raise ValueError("This operation requires Proxmox VE 9.x")
    resources = json.loads(
        command("pvesh", "get", "/cluster/resources", "--output-format", "json")
    )
    if any(item.get("type") in {"qemu", "lxc"} for item in resources):
        raise ValueError("Existing workloads prevent renaming")
    current = socket.gethostname()
    if current not in {previous, desired}:
        raise ValueError("Unexpected current hostname")
    nodes = Path("/etc/pve/nodes")
    if any(node.name not in {previous, desired} for node in nodes.iterdir()):
        raise ValueError("Unexpected additional node configuration")
    if current == previous and (nodes / desired).exists():
        raise ValueError("The destination node already exists")
    validate_node(nodes / previous)
    storage = Path("/etc/pve/storage.cfg").read_text()
    if re.search(r"^\s*nodes\s+", storage, re.MULTILINE):
        raise ValueError("Node-specific storage restrictions require a separate plan")
    hostname = Path("/etc/hostname")
    hosts = Path("/etc/hosts")
    replacements = {
        hostname: desired + "\n",
        hosts: rewrite_hosts(hosts.read_text(), previous, desired, address),
    }
    mail = command("postconf", "-h", "myhostname")
    desired_mail = (
        desired + mail[len(previous) :]
        if mail == previous or mail.startswith(previous + ".")
        else mail
    )
    changed = (
        any(path.read_text() != text for path, text in replacements.items())
        or mail != desired_mail
    )
    reboot = current != desired or Path("/etc/pve/local").resolve().name != desired
    archive = (
        current == desired
        and not reboot
        and previous != desired
        and (nodes / previous).exists()
    )
    result = {
        "hostname": current,
        "desired_hostname": desired,
        "changed": changed or archive,
        "reboot_required": reboot,
        "archive_old_node": archive,
    }
    if action == "plan":
        return result
    backup = Path("/var/backups/milkyway-hostname") / previous
    if backup.is_symlink() or backup.parent.is_symlink():
        raise ValueError("Backup path must not be a symlink")
    backup.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup.chmod(0o700)
    for source in (*replacements, Path("/etc/postfix/main.cf")):
        destination = backup / source.name
        if not destination.exists():
            shutil.copy2(source, destination)
    for path, text in replacements.items():
        if path.read_text() != text:
            path.write_text(text)
    if mail != desired_mail:
        command("postconf", "-e", "myhostname=" + desired_mail)
    if archive:
        destination = backup / "node"
        if destination.exists():
            raise ValueError("Old-node backup already exists; refusing to replace it")
        shutil.move(str(nodes / previous), str(destination))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "apply"])
    parser.add_argument("--previous-hostname", required=True)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--hostname")
    parser.add_argument("--address")
    args = parser.parse_args()
    try:
        previous = args.previous_hostname
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", previous):
            raise ValueError("Invalid previous hostname")
        if args.remote:
            if not args.hostname or not re.fullmatch(
                r"[a-z0-9][a-z0-9-]{0,62}", args.hostname
            ):
                raise ValueError("Invalid desired hostname")
            ipaddress.IPv4Address(args.address)
            print(
                json.dumps(remote(args.action, previous, args.hostname, args.address))
            )
        else:
            from proxmox_preflight import host_config, ssh_args

            host = host_config(args.inventory)
            ipaddress.IPv4Address(host["address"])
            ssh = ssh_args(host)
            ssh[-1] = shlex.join(
                [
                    "python3",
                    "-",
                    args.action,
                    "--remote",
                    "--previous-hostname",
                    previous,
                    "--hostname",
                    host["expected_hostname"],
                    "--address",
                    host["address"],
                ]
            )
            result = subprocess.run(
                ssh,
                input=Path(__file__).read_text(),
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
            print(result.stdout.strip())
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        # Do not expose arbitrary remote output or private configuration.
        raise SystemExit(
            f"Hostname operation failed ({type(exc).__name__}); inspect the reviewed prerequisites"
        ) from None


if __name__ == "__main__":
    main()

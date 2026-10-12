"""Keep a laptop Proxmox bootstrap host awake when its lid closes."""

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

SETTINGS = ("HandleLidSwitch", "HandleLidSwitchExternalPower", "HandleLidSwitchDocked")
CONTENT = "[Login]\n" + "".join(f"{name}=ignore\n" for name in SETTINGS)
DESTINATION = Path("/etc/systemd/logind.conf.d/90-milkyway-lid.conf")


def run(*args):
    return subprocess.run(
        args, check=True, capture_output=True, text=True
    ).stdout.strip()


def check_overrides(text, destination):
    source = None
    for line in text.splitlines():
        if line.startswith("# /"):
            source = line[2:]
        match = re.fullmatch(
            r"\s*(HandleLidSwitch(?:ExternalPower|Docked)?)\s*=\s*(\S+)\s*", line
        )
        if match and match[2] != "ignore" and source != str(destination):
            raise ValueError(
                "An existing lid policy requires review before replacement"
            )


def configure(action, destination=DESTINATION):
    if destination.is_symlink():
        raise ValueError("Refusing a symlink at the managed configuration path")
    check_overrides(
        run("systemd-analyze", "cat-config", "systemd/logind.conf"), destination
    )
    changed = not destination.exists() or destination.read_text() != CONTENT
    if destination.exists():
        metadata = destination.stat()
        changed = (
            changed
            or metadata.st_mode & 0o777 != 0o644
            or metadata.st_uid != 0
            or metadata.st_gid != 0
        )
    if action == "apply" and changed:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", dir=destination.parent, delete=False
        ) as temporary:
            temporary.write(CONTENT)
            temporary.flush()
            os.fchmod(temporary.fileno(), 0o644)
            os.fchown(temporary.fileno(), 0, 0)
        Path(temporary.name).replace(destination)
    return {
        "changed": changed,
        "applied": action == "apply",
        "lid_actions": {name: "ignore" for name in SETTINGS},
    }


def remote(action, hostname):
    if os.geteuid() != 0 or socket.gethostname() != hostname:
        raise ValueError("Root access and the expected hostname are required")
    if (
        not run("pveversion").startswith("pve-manager/9.")
        or Path("/etc/pve/corosync.conf").exists()
    ):
        raise ValueError("Lid bootstrap requires a standalone Proxmox VE 9 node")
    resources = json.loads(
        run("pvesh", "get", "/cluster/resources", "--output-format", "json")
    )
    if any(item.get("type") in {"qemu", "lxc"} for item in resources):
        raise ValueError("Existing workloads require a maintenance plan")
    if not Path("/proc/acpi/button/lid").is_dir():
        raise ValueError("No ACPI lid switch was detected")
    result = configure(action)
    boot_time = time.time() - float(Path("/proc/uptime").read_text().split()[0])
    result["reboot_required"] = (
        DESTINATION.exists() and DESTINATION.stat().st_mtime > boot_time
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "apply"])
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
                timeout=60,
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
            f"Lid configuration failed ({type(exc).__name__}); inspect host prerequisites without exposing credentials"
        ) from None


if __name__ == "__main__":
    main()

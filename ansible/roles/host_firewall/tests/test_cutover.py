"""Exercise real firewall preflight and rendering against temporary policies."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(
    not shutil.which("ansible-playbook"), reason="Ansible is required"
)


@pytest.fixture(params=["guest", "native"])
def firewall(request, tmp_path):
    kind = request.param
    role = ROOT / "roles" / ("host_firewall" if kind == "guest" else "proxmox_access")
    source = role / "tasks" / ("main.yml" if kind == "guest" else "firewall.yml")
    tasks = yaml.safe_load(source.read_text())
    stop = "Install nftables" if kind == "guest" else "Write cluster candidate"
    tasks = tasks[: next(i for i, task in enumerate(tasks) if task["name"] == stop)]
    paths = {
        "/etc/nftables.d/milkyway.nft": str(tmp_path / "installed-policy"),
        "/etc/pve/corosync.conf": str(tmp_path / "corosync.conf"),
        "/etc/pve/firewall/cluster.fw": str(tmp_path / "cluster.fw"),
        "/etc/pve/nodes/{{ proxmox_node }}/host.fw": str(tmp_path / "installed-policy"),
    }

    def isolate(value):
        if isinstance(value, str):
            return paths.get(value, value)
        if isinstance(value, list):
            return [isolate(item) for item in value]
        if isinstance(value, dict):
            return {key: isolate(item) for key, item in value.items()}
        return value

    tasks = isolate(tasks)
    verifier = tmp_path / "roles" / "ssh_access" / "tasks"
    verifier.mkdir(parents=True)
    (verifier / "verify.yml").write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Require a discovered and freshly verified tailnet path",
                    "ansible.builtin.assert": {
                        "that": [
                            "platform_tailnet_address is defined",
                            "platform_tailnet_address is match('^100\\.')",
                            "fixture_fresh_tailnet | bool",
                        ],
                        "fail_msg": "Fresh tailnet verification failed",
                    },
                }
            ]
        )
    )
    template = (
        role / "templates" / ("milkyway.nft.j2" if kind == "guest" else "host.fw.j2")
    )
    candidate = tmp_path / "candidate"
    tasks.append(
        {
            "name": "Render the real candidate after successful preflight",
            "ansible.builtin.template": {
                "src": str(template),
                "dest": str(candidate),
                "mode": "0600",
            },
        }
    )
    config = tmp_path / "ansible.cfg"
    config.write_text("[defaults]\n")
    env = {
        key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ
    }
    env.update(
        {
            "HOME": str(tmp_path),
            "ANSIBLE_CONFIG": str(config),
            "ANSIBLE_ROLES_PATH": str(tmp_path / "roles"),
            "ANSIBLE_FILTER_PLUGINS": str(ROOT / "filter_plugins"),
            "ANSIBLE_LOCAL_TEMP": str(tmp_path / "local"),
            "ANSIBLE_REMOTE_TEMP": str(tmp_path / "remote"),
            "ANSIBLE_NOCOLOR": "1",
            "ANSIBLE_PYTHON_INTERPRETER": sys.executable,
        }
    )
    policy = tmp_path / "installed-policy"
    bootstrap_line = (
        "        ip saddr 192.0.2.100/32 tcp dport 22 accept\n"
        if kind == "guest"
        else "IN ACCEPT -source 192.0.2.100/32 -p tcp -dport 22,8006\n"
    )

    class Fixture:
        def seed(self, *, opened):
            policy.write_text(
                "# Managed by MilkyWay\n" + (bootstrap_line if opened else "")
            )

        def run(
            self,
            *,
            mode="bootstrap",
            requested=False,
            fresh=True,
            discovered=True,
            failure=False,
        ):
            before = policy.read_bytes() if policy.exists() else None
            candidate.unlink(missing_ok=True)
            variables = {
                "host_firewall_cutover": requested,
                "proxmox_firewall_cutover": requested,
                "platform_access_mode": mode,
                "platform_initial_management_cidr": "192.0.2.100/32",
                "proxmox_node": "fixture",
                "ansible_managed": "Managed by MilkyWay",
                "fixture_fresh_tailnet": fresh,
            }
            if discovered:
                variables["platform_tailnet_address"] = "100.64.0.10"
            play = [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "vars": variables,
                    "tasks": tasks,
                }
            ]
            path = tmp_path / "play.yml"
            path.write_text(yaml.safe_dump(play, sort_keys=False))
            result = subprocess.run(
                ["ansible-playbook", "-i", "localhost,", str(path)],
                capture_output=True,
                text=True,
                env=env,
                timeout=60,
                check=False,
            )
            if failure:
                assert result.returncode != 0, result.stdout + result.stderr
                assert "Fresh tailnet verification failed" in result.stdout
                assert not candidate.exists()
            else:
                assert result.returncode == 0, result.stdout + result.stderr
                assert candidate.exists()
            assert (policy.read_bytes() if policy.exists() else None) == before
            return candidate.read_bytes() if candidate.exists() else None

        def assert_bootstrap(self, rendered, *, opened):
            assert (bootstrap_line.strip().encode() in rendered) == opened

        def commit_candidate(self):
            shutil.copyfile(candidate, policy)

    return Fixture()


def test_initial_bootstrap_does_not_require_tailnet(firewall):
    rendered = firewall.run(fresh=False, discovered=False)
    firewall.assert_bootstrap(rendered, opened=True)
    firewall.seed(opened=True)
    firewall.assert_bootstrap(firewall.run(fresh=False, discovered=False), opened=True)


def test_cutover_and_bootstrap_retry_preserve_closed_policy(firewall):
    firewall.seed(opened=True)
    closed = firewall.run(requested=True)
    firewall.assert_bootstrap(closed, opened=False)
    firewall.commit_candidate()
    repeated = firewall.run(mode="bootstrap", requested=False)
    assert repeated == closed
    firewall.assert_bootstrap(repeated, opened=False)


def test_operational_mode_closes_bootstrap_policy(firewall):
    firewall.seed(opened=True)
    firewall.assert_bootstrap(firewall.run(mode="operational"), opened=False)


@pytest.mark.parametrize(
    "mode,requested,opened,discovered",
    [
        ("bootstrap", True, True, True),
        ("bootstrap", False, False, True),
        ("operational", False, True, False),
    ],
)
def test_failed_private_precheck_never_writes_policy(
    firewall, mode, requested, opened, discovered
):
    firewall.seed(opened=opened)
    firewall.run(
        mode=mode,
        requested=requested,
        fresh=False,
        discovered=discovered,
        failure=True,
    )

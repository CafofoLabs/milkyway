"""Validate application identities and run native OpenTofu with protected artifacts."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"[a-z][a-z0-9-]{0,47}\Z")
SEGMENT = re.compile(r"[a-zA-Z0-9_-]+\Z")


class ContractError(ValueError):
    """Invalid or unauthorized request. Messages never include supplied values."""


class UniqueLoader(yaml.SafeLoader):
    pass


def mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise ContractError("YAML keys must be unique strings")
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def load(path):
    try:
        return yaml.load(Path(path).read_text(), Loader=UniqueLoader)
    except (yaml.YAMLError, RecursionError) as error:
        raise ContractError("Invalid YAML document") from error


def fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys():
        raise ContractError("Missing required object fields")
    if value.keys() - set(required) - set(optional):
        raise ContractError("Unknown object fields are not supported")
    return value


def name(value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ContractError("Names must be lowercase slugs of at most 48 characters")
    return value


def strings(value):
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ContractError("Expected a string list")
    if len(set(value)) != len(value):
        raise ContractError("Duplicate list entries")
    return value


def read_rule(value):
    fields(value, ("mount", "path"), ("recursive",))
    name(value["mount"])
    path = value["path"]
    if not isinstance(path, str) or not all(
        SEGMENT.fullmatch(p) for p in path.split("/")
    ):
        raise ContractError(
            "Secret paths must contain literal segments without wildcards"
        )
    recursive = value.get("recursive", False)
    if type(recursive) is not bool:
        raise ContractError("recursive must be boolean")
    return {"mount": value["mount"], "path": path, "recursive": recursive}


def permits(grant, request):
    return grant["mount"] == request["mount"] and (
        (
            grant["path"] == request["path"]
            and (grant["recursive"] or not request["recursive"])
        )
        or (grant["recursive"] and request["path"].startswith(grant["path"] + "/"))
    )


def catalog(document):
    fields(
        document,
        ("version", "deployment", "identity", "openbao", "roles", "applications"),
    )
    if type(document["version"]) is not int or document["version"] != 1:
        raise ContractError("Unsupported catalog version")
    name(document["deployment"])
    identity = fields(
        document["identity"],
        (
            "url",
            "slug",
            "signingKey",
            "authorizationFlow",
            "invalidationFlow",
            "jwtTtl",
        ),
    )
    bao = fields(document["openbao"], ("url", "authMount", "tokenTtl", "tokenMaxTtl"))
    for url in (identity["url"], bao["url"]):
        if not isinstance(url, str):
            raise ContractError("Endpoints must be HTTPS origins")
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ContractError(
                "Endpoints must be HTTPS origins without credentials or paths"
            )
    name(identity["slug"])
    name(bao["authMount"])
    if bao["authMount"] in {"oidc", "approle", "token"}:
        raise ContractError("A dedicated machine JWT mount is required")
    for key in ("signingKey", "authorizationFlow", "invalidationFlow"):
        if not isinstance(identity[key], str) or not identity[key].strip():
            raise ContractError("Identity key and flow names are required")
    for ttl in (identity["jwtTtl"], bao["tokenTtl"], bao["tokenMaxTtl"]):
        if type(ttl) is not int or not 60 <= ttl <= 3600:
            raise ContractError("Token lifetimes must be between 60 and 3600 seconds")
    if bao["tokenTtl"] > bao["tokenMaxTtl"]:
        raise ContractError("Token TTL exceeds its maximum")
    if not isinstance(document["roles"], dict) or not document["roles"]:
        raise ContractError("Define at least one access profile")
    for role, profile in document["roles"].items():
        name(role)
        fields(profile, ("policies",))
        for policy in strings(profile["policies"]):
            name(policy)
            if policy in {"root", "default"}:
                raise ContractError(
                    "Reserved OpenBao policies are not application profiles"
                )
    applications = document["applications"]
    if not isinstance(applications, dict) or not applications:
        raise ContractError("Define authorized application/environment pairs")
    namespaces = set()
    for app, environments in applications.items():
        name(app)
        if not isinstance(environments, dict) or not environments:
            raise ContractError("Define application environments")
        for env, grant in environments.items():
            name(env)
            namespace = f"{app}-{env}"
            if namespace in namespaces:
                raise ContractError(
                    "Application/environment names produce conflicting account namespaces"
                )
            namespaces.add(namespace)
            fields(grant, ("roles", "secrets"))
            if not set(strings(grant["roles"])) <= document["roles"].keys():
                raise ContractError("Catalog references an undefined role")
            if not isinstance(grant["secrets"], list):
                raise ContractError("Secret grants must be a list")
            for rule in grant["secrets"]:
                read_rule(rule)
    return document


def compile_contract(document, environment_catalog):
    fields(document, ("version", "application", "environment", "serviceAccounts"))
    if type(document["version"]) is not int or document["version"] != 1:
        raise ContractError("Unsupported application contract version")
    app, env = name(document["application"]), name(document["environment"])
    try:
        grant = environment_catalog["applications"][app][env]
    except KeyError as error:
        raise ContractError(
            "Application/environment is not authorized by this catalog"
        ) from error
    accounts = document["serviceAccounts"]
    if not isinstance(accounts, list):
        raise ContractError("serviceAccounts must be a list")
    compiled = {}
    for account in accounts:
        fields(account, ("name", "roles"), ("enabled", "secrets", "credentialRevision"))
        username = account["name"]
        prefix = f"svc-{app}-{env}"
        if (
            not isinstance(username, str)
            or not re.fullmatch(r"[a-z][a-z0-9-]{0,159}", username)
            or not (username == prefix or username.startswith(prefix + "-"))
        ):
            raise ContractError(
                "Service account name must start with svc-<application>-<environment>"
            )
        owners = [
            (registered_app, registered_env)
            for registered_app, environments in environment_catalog[
                "applications"
            ].items()
            for registered_env in environments
            if username == f"svc-{registered_app}-{registered_env}"
            or username.startswith(f"svc-{registered_app}-{registered_env}-")
        ]
        if owners != [(app, env)]:
            raise ContractError(
                "Service account name overlaps another registered namespace"
            )
        if username in compiled:
            raise ContractError("Duplicate service account")
        enabled = account.get("enabled", True)
        revision = account.get("credentialRevision", 1)
        if (
            type(enabled) is not bool
            or type(revision) is not int
            or not 1 <= revision <= 2147483647
        ):
            raise ContractError(
                "enabled must be boolean and credentialRevision a positive integer"
            )
        roles = strings(account["roles"])
        if not set(roles) <= set(grant["roles"]):
            raise ContractError("Requested role is not authorized")
        secrets = fields(account.get("secrets", {"read": []}), ("read",))
        if not isinstance(secrets["read"], list):
            raise ContractError("Secret read requests must be a list")
        reads = [read_rule(rule) for rule in secrets["read"]]
        if len({json.dumps(r, sort_keys=True) for r in reads}) != len(reads):
            raise ContractError("Duplicate secret read rule")
        allowed = [read_rule(rule) for rule in grant["secrets"]]
        if any(not any(permits(g, r) for g in allowed) for r in reads):
            raise ContractError("Requested secret path is not authorized")
        compiled[username] = {
            "enabled": enabled,
            "roles": sorted(roles),
            "reads": reads,
            "credential_revision": revision,
        }
    return {
        "application": app,
        "environment": env,
        "deployment": environment_catalog["deployment"],
        "profiles": {r: environment_catalog["roles"][r] for r in grant["roles"]},
        "accounts": compiled,
    }


def settings(config):
    identity, bao = config["identity"], config["openbao"]
    return {
        "deployment": config["deployment"],
        "identity_url": identity["url"],
        "vault_url": bao["url"],
        "slug": identity["slug"],
        "auth_mount": bao["authMount"],
        "signing_key": identity["signingKey"],
        "authorization_flow": identity["authorizationFlow"],
        "invalidation_flow": identity["invalidationFlow"],
        "jwt_ttl": identity["jwtTtl"],
        "token_ttl": bao["tokenTtl"],
        "token_max_ttl": bao["tokenMaxTtl"],
    }


def private_directory(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ContractError("Private workspace cannot contain symlinks")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def private_write(path, content):
    path = Path(path)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as target:
        temporary = Path(target.name)
        try:
            os.fchmod(target.fileno(), 0o600)
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def tofu(directory, *arguments, output=None):
    # Provider errors can contain credentials. Never relay their output or enable
    # tracing; a failing operation is identified by command, without its payload.
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith(("TF_LOG", "TF_CLI_ARGS")):
            del environment[key]
    environment.update(TF_IN_AUTOMATION="1", TF_INPUT="0")
    result = subprocess.run(
        ["tofu", f"-chdir={directory}", *arguments],
        env=environment,
        stdout=output or subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=600,
        check=False,
    )
    if result.returncode:
        raise ContractError(
            f"OpenTofu {arguments[0]} failed; output suppressed to protect credentials"
        )
    return result.stdout


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


@contextlib.contextmanager
def operation_lock(directory):
    descriptor = os.open(
        directory / "operation.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ContractError(
                "Another identity operation holds this workspace"
            ) from error
        previous_umask = os.umask(0o077)
        try:
            yield
        finally:
            os.umask(previous_umask)


def execute(action, config, contract, workspace, component):
    inputs = {"settings": settings(config)}
    if contract is not None:
        inputs["contract"] = contract
    key = (
        "foundation"
        if component == "foundation"
        else f"applications/{contract['application']}/{contract['environment']}"
    )
    base = private_directory(workspace)
    base = private_directory(base / config["deployment"])
    directory = private_directory(base / key)
    with operation_lock(directory):
        template = (
            ROOT
            / "examples"
            / ("machine-identity" if component == "foundation" else "service-accounts")
            / "main.tf"
        )
        source = (
            ROOT
            / "tofu/modules"
            / (
                "machine-identity"
                if component == "foundation"
                else "service-account-access"
            )
        )
        configuration = template.read_text().replace("MODULE_SOURCE", str(source))
        providers = template.with_name(".terraform.lock.hcl").read_text()
        fingerprint = digest(
            {
                "inputs": inputs,
                "root": configuration,
                "providers": providers,
                "module": {p.name: p.read_text() for p in sorted(source.glob("*.tf"))},
            }
        )
        plan, receipt = directory / "identity.tfplan", directory / "plan.json"
        if action == "apply":
            if not plan.is_file() or not receipt.is_file():
                raise ContractError("Create and review a saved plan before applying")
            saved = json.loads(receipt.read_text())
            if (
                saved["fingerprint"] != fingerprint
                or saved["plan_hash"] != hashlib.sha256(plan.read_bytes()).hexdigest()
            ):
                raise ContractError(
                    "Plan, manifest, catalog or framework changed; create a new plan"
                )
            tofu(directory, "apply", "-input=false", "-no-color", str(plan))
            export_credentials(directory, config, contract, component)
            private_write(
                directory / "applied.json", json.dumps({"fingerprint": fingerprint})
            )
            receipt.unlink()
            plan.unlink()
            print(
                "Applied the saved identity plan; protected deployment artifacts updated."
            )
            return
        if action == "verify":
            applied = directory / "applied.json"
            if (
                not applied.is_file()
                or json.loads(applied.read_text())["fingerprint"] != fingerprint
            ):
                raise ContractError("Apply the current contract before verification")
            tofu(directory, "plan", "-detailed-exitcode", "-input=false", "-no-color")
            if component == "foundation":
                print(
                    "Foundation is converged. Application verification checks authentication separately."
                )
            else:
                from service_identity_runtime import verify

                verify(directory / "deployment.json", contract)
                print(
                    "Identity authentication and declared secret permissions verified."
                )
            return
        private_write(directory / "main.tf", configuration)
        private_write(directory / ".terraform.lock.hcl", providers)
        private_write(directory / "contract.auto.tfvars.json", json.dumps(inputs))
        tofu(directory, "init", "-input=false", "-no-color", "-lockfile=readonly")
        tofu(directory, "validate", "-no-color")
        tofu(directory, "plan", "-input=false", "-no-color", f"-out={plan}")
        plan.chmod(0o600)
        # The JSON rendering contains secrets; only an allowlisted summary is
        # published. Raw stdout never reaches the caller or a log file.
        rendered = json.loads(tofu(directory, "show", "-json", str(plan)))
        changes = [
            {"address": r["address"], "actions": r["change"]["actions"]}
            for r in rendered.get("resource_changes", [])
            if r["change"]["actions"] != ["no-op"]
        ]
        private_write(
            receipt,
            json.dumps(
                {
                    "fingerprint": fingerprint,
                    "plan_hash": hashlib.sha256(plan.read_bytes()).hexdigest(),
                }
            ),
        )
        print(json.dumps({"component": component, "changes": changes}, indent=2))


def export_credentials(directory, config, contract, component):
    if component == "foundation":
        return
    # All values remain in a subprocess pipe and a private file. They are never
    # printed or included in plan summaries. The file is a deployment input.
    credentials = json.loads(tofu(directory, "output", "-json", "credentials"))
    connection = settings(config)
    private_write(
        directory / "deployment.json",
        json.dumps(
            {
                "connection": {
                    "client_id": connection["slug"],
                    "token_url": connection["identity_url"] + "/application/o/token/",
                    "vault_url": connection["vault_url"],
                    "auth_mount": connection["auth_mount"],
                    "scope": "milkyway-service",
                },
                "accounts": credentials,
            }
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "plan", "apply", "verify"))
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--component", choices=("foundation", "application"), default="application"
    )
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    try:
        config = catalog(load(args.catalog))
        if args.component == "application" and args.manifest is None:
            raise ContractError("Application operations require --manifest")
        contract = (
            compile_contract(load(args.manifest), config)
            if args.component == "application"
            else None
        )
        if args.action == "validate":
            print("Identity contract and catalog are valid and authorized.")
        else:
            if args.workspace is None:
                raise ContractError(
                    "Execution requires an explicit private --workspace"
                )
            execute(args.action, config, contract, args.workspace, args.component)
    except ContractError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        # Do not expose YAML/parser/provider exception payloads or file contents.
        print(
            "Identity operation failed. Check contract, catalog, saved plan and prerequisites; credential output is suppressed.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

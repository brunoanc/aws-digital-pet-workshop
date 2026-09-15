"""Review and update app access without changing application code."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import shlex

from app.access import load_policy
from scripts.deploy_proxy import verified_session


def remote_update(request):
    """Check the policy hash, keep a backup and replace the file atomically."""

    import fcntl
    import os
    import sys
    import tempfile

    sys.path.insert(0, "/opt/workshop-login")

    from app.access import load_policy

    target = Path("/etc/workshop-login/access.json")

    with open("/run/workshop-login-access.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

        if target.is_symlink() or not target.is_file():
            raise ValueError("The policy must be an existing regular file.")

        previous = target.read_bytes()
        fingerprint = hashlib.sha256(previous).hexdigest()

        if request["policy"] is None:
            return {"fingerprint": fingerprint, "policy": json.loads(previous)}

        if fingerprint != request["expected"]:
            raise ValueError("The policy changed after review.")

        current = load_policy(target)
        descriptor, candidate = tempfile.mkstemp(prefix=".access-", dir=target.parent)

        try:
            with os.fdopen(descriptor, "w") as output:
                json.dump(request["policy"], output, indent=2)
                output.flush()
                os.fsync(output.fileno())

            proposed = load_policy(candidate)

            if (proposed.issuer, proposed.client_id) != (
                current.issuer,
                current.client_id,
            ):
                raise ValueError(
                    "The update must retain the installed identity provider and client."
                )

            backup = target.parent / ("access-backup-" + fingerprint + ".json")

            if not backup.exists():
                with open(
                    backup, "xb", opener=lambda path, flags: os.open(path, flags, 0o600)
                ) as output:
                    output.write(previous)
                    output.flush()
                    os.fsync(output.fileno())

            if backup.is_symlink() or backup.read_bytes() != previous:
                raise ValueError(
                    "The existing backup does not match the reviewed policy."
                )

            metadata = target.stat()

            os.chown(candidate, metadata.st_uid, metadata.st_gid)
            os.chmod(candidate, 0o640)
            os.replace(candidate, target)

            return {
                "status": "updated",
                "backup": backup.name,
                "fingerprint": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        finally:
            if os.path.exists(candidate):
                os.unlink(candidate)


def build(policy, expected):
    """Build a policy command for the server's Python runtime."""

    import inspect
    import re

    if policy is not None and (
        not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected)
    ):
        raise ValueError("Provide the policy fingerprint reviewed before the update.")

    request = base64.b64encode(
        json.dumps({"policy": policy, "expected": expected}).encode()
    ).decode()
    source = (
        "import json,base64,hashlib\nfrom pathlib import Path\n"
        + inspect.getsource(remote_update)
    )
    source += f"\nprint(json.dumps(remote_update(json.loads(base64.b64decode('{request}')))))\n"
    payload = base64.b64encode(source.encode()).decode()

    return "/opt/workshop-login/venv/bin/python -c " + shlex.quote(
        f"import base64; exec(base64.b64decode('{payload}'))"
    )


def main():
    """Preview or send a policy command after checking the host."""

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--proxy-config", required=True)
    parser.add_argument("--policy")
    parser.add_argument("--expected")
    parser.add_argument("--apply", action="store_true")

    args = parser.parse_args()
    proxy = json.loads(Path(args.proxy_config).read_text())
    policy = None

    if args.policy:
        load_policy(args.policy)

        policy = json.loads(Path(args.policy).read_text())

    command = build(policy, args.expected)

    if not args.apply:
        print(
            json.dumps(
                {
                    "instance_id": proxy["instance_id"],
                    "policy": policy,
                    "expected": args.expected,
                    "command_sha256": hashlib.sha256(command.encode()).hexdigest(),
                }
            )
        )

        return

    result = verified_session(proxy).send_command(
        InstanceIds=[proxy["instance_id"]],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [command], "executionTimeout": ["60"]},
        TimeoutSeconds=60,
        Comment="Review or update isolated login authorization",
    )

    print(json.dumps({"command_id": result["Command"]["CommandId"]}))


if __name__ == "__main__":
    main()

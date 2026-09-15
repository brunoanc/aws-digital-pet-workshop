"""Package or restore the shared app without including secrets."""

import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import re
import shlex

from app.shared_card import load_targets
from scripts.deploy_proxy import commands, verified_session


ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "app/__init__.py",
    "app/access.py",
    "app/login_ui.py",
    "app/shared_ui.py",
    "app/shared_card.py",
    "app/card_limits.py",
    "app/shared_agent.py",
    "app/remote.py",
    "app/remote_ui.py",
    "app/browser_url.py",
    "app/function_url.py",
    "app/card.py",
    "app/backend.py",
    "app/scene.py",
    "app/species.py",
    "scripts/login_runtime.py",
)


def build(proxy, mode, targets=None, expected=None, backup=None):
    """Build the release command from approved files without student Lambda code."""

    commands(proxy)

    if mode not in ("status", "update", "rollback"):
        raise ValueError("Choose status, update, or rollback.")

    if mode != "status" and (
        not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected)
    ):
        raise ValueError("Provide the reviewed service fingerprint.")

    if mode == "rollback" and (
        not isinstance(backup, str) or not re.fullmatch(r"release-[a-z0-9_]{8}", backup)
    ):
        raise ValueError("Provide a valid login backup identifier.")

    bundle = {
        "mode": mode,
        "expected": expected,
        "backup": backup,
        "helper": (ROOT / "scripts/proxy_release.py").read_text(),
    }

    if mode == "update":
        if targets is None or any(
            targets[key] != proxy[key] for key in ("account_id", "region")
        ):
            raise ValueError(
                "The card destinations must match the host account and region."
            )

        files = {name: (ROOT / name).read_text() for name in MODULES}

        files.update(
            {
                str(path.relative_to(ROOT)): path.read_text()
                for path in (ROOT / "app/assets").iterdir()
                if path.suffix in (".svg", ".css", ".html", ".js")
            }
        )

        files[".streamlit/config.toml"] = (
            (ROOT / "hosting/login-config.toml.template")
            .read_text()
            .replace("@@DOMAIN@@", proxy["domain"])
            .replace("@@THEME@@", (ROOT / ".streamlit/config.toml").read_text())
        )

        bundle.update(
            files=files,
            targets=targets,
            service=(ROOT / "hosting/login.service").read_text(),
        )

    payload = base64.b64encode(
        gzip.compress(json.dumps(bundle).encode(), mtime=0)
    ).decode()
    source = base64.b64encode(
        (ROOT / "scripts/shared_release.py").read_bytes()
    ).decode()
    runner = f"import base64,sys; sys.argv=['shared-release','{payload}']; exec(compile(base64.b64decode('{source}'),'shared-release','exec'))"
    command = "python3 -c " + shlex.quote(runner)

    if len(command.encode()) > 60000:
        raise ValueError("The shared release exceeds the bounded command size.")

    return command


def main():
    """Preview or send a release command after checking the host."""

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--proxy-config", required=True)
    parser.add_argument("--targets")
    parser.add_argument(
        "--mode", choices=("status", "update", "rollback"), required=True
    )
    parser.add_argument("--expected")
    parser.add_argument("--backup")
    parser.add_argument("--apply", action="store_true")

    args = parser.parse_args()
    proxy = json.loads(Path(args.proxy_config).read_text())
    targets = load_targets(args.targets) if args.targets else None
    command = build(proxy, args.mode, targets, args.expected, args.backup)

    if not args.apply:
        print(
            json.dumps(
                {
                    "mode": args.mode,
                    "instance_id": proxy["instance_id"],
                    "targets": targets,
                    "expected": args.expected,
                    "backup": args.backup,
                    "command_sha256": hashlib.sha256(command.encode()).hexdigest(),
                    "bytes": len(command.encode()),
                }
            )
        )

        return

    result = verified_session(proxy).send_command(
        InstanceIds=[proxy["instance_id"]],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [command], "executionTimeout": ["240"]},
        TimeoutSeconds=60,
        Comment="Deploy or recover read-only workshop pet card",
    )

    print(json.dumps({"command_id": result["Command"]["CommandId"]}))


if __name__ == "__main__":
    main()

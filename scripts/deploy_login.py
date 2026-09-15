"""Package the standalone login and install it through SSM after review."""

import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

from scripts.deploy_proxy import commands, verified_session
from scripts.initialize_login_secret import validate_config


ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "app/__init__.py",
    "app/access.py",
    "app/login_ui.py",
    "scripts/login_runtime.py",
)


def build(proxy, login):
    """Package the login with pinned dependencies, no secrets and access disabled."""

    commands(proxy)
    validate_config(login)

    if (
        any(proxy[key] != login[key] for key in ("account_id", "region", "profile"))
        or login["app_origin"] != "https://" + proxy["domain"]
    ):
        raise ValueError(
            "The host and login configuration must use the same account, region, profile, and domain."
        )

    requirements = subprocess.run(
        [
            "uv",
            "export",
            "--locked",
            "--offline",
            "--no-dev",
            "--no-emit-project",
            "--prune",
            "strands-agents",
            "--no-header",
            "--no-annotate",
            "--format",
            "requirements.txt",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout
    files = {name: (ROOT / name).read_text() for name in FILES}
    files["requirements.txt"] = requirements
    files[".streamlit/config.toml"] = (
        (ROOT / "hosting/login-config.toml.template")
        .read_text()
        .replace("@@DOMAIN@@", proxy["domain"])
        .replace("@@THEME@@", (ROOT / ".streamlit/config.toml").read_text())
    )
    bundle = {
        "files": files,
        "service": (ROOT / "hosting/login.service").read_text(),
        "runtime": {key: value for key, value in login.items() if key != "profile"},
        "access": {
            "issuer": f"https://cognito-idp.{login['region']}.amazonaws.com/{login['user_pool_id']}",
            "client_id": login["client_id"],
            "enabled": False,
            "opens_at": 0,
            "closes_at": 1,
            "max_session_seconds": 3600,
            "teams": ["team-01", "team-02"],
            "members": {},
        },
    }
    payload = base64.b64encode(
        gzip.compress(json.dumps(bundle).encode(), mtime=0)
    ).decode()
    source = base64.b64encode((ROOT / "scripts/install_login.py").read_bytes()).decode()
    runner = f"import base64,sys; sys.argv=['install-login','{payload}']; exec(compile(base64.b64decode('{source}'),'install-login','exec'))"
    command = "python3 -c " + shlex.quote(runner)

    if len(command.encode()) > 60000:
        raise ValueError("The login bundle exceeds the bounded SSM command size.")

    return command


def main():
    """Preview the command hash or install the login after checking the host."""

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--proxy-config", required=True)
    parser.add_argument("--login-config", required=True)
    parser.add_argument("--apply", action="store_true")

    args = parser.parse_args()
    proxy = json.loads(Path(args.proxy_config).read_text())
    login = json.loads(Path(args.login_config).read_text())
    command = build(proxy, login)

    if not args.apply:
        print(
            json.dumps(
                {
                    "instance_id": proxy["instance_id"],
                    "command_sha256": hashlib.sha256(command.encode()).hexdigest(),
                    "bytes": len(command.encode()),
                    "scope": "first-login-install-no-proxy-change",
                }
            )
        )

        return

    result = verified_session(proxy).send_command(
        InstanceIds=[proxy["instance_id"]],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [command], "executionTimeout": ["1200"]},
        TimeoutSeconds=60,
        Comment="Install isolated workshop login without changing HTTPS routing",
    )

    print(json.dumps({"command_id": result["Command"]["CommandId"]}))


if __name__ == "__main__":
    main()

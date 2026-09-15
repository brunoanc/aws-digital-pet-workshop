"""Install, update or restore the proxy without sending secrets through SSM."""

import argparse
import base64
import hashlib
import http.client
import json
from pathlib import Path
import re
import shlex

import boto3
from botocore.config import Config


ROOT = Path(__file__).resolve().parents[1]


def proxy_files(config):
    """Build the proxy config and service unit for the selected route."""

    route = config.get("route", "maintenance")

    if route not in ("maintenance", "login"):
        raise ValueError("Choose maintenance or login for the public route.")

    template = "Caddyfile.login.template" if route == "login" else "Caddyfile.template"

    return {
        "Caddyfile": (ROOT / "hosting" / template)
        .read_text()
        .replace("@@DOMAIN@@", config["domain"]),
        "service": (ROOT / "hosting/caddy.service").read_text(),
    }


def commands(config):
    """Build the installer with binary hash checks and proxy-owned config files."""

    patterns = {
        "account_id": r"[0-9]{12}",
        "region": r"us-[a-z]+-[0-9]+",
        "instance_id": r"i-[a-f0-9]{17}",
        "instance_name": r"[a-z][a-z0-9-]{2,39}",
        "domain": r"[a-z0-9][a-z0-9.-]+\.[a-z]{2,}",
        "version": r"[0-9]+\.[0-9]+\.[0-9]+",
        "sha256": r"[a-f0-9]{64}",
    }

    if (
        not isinstance(config, dict)
        or set(config) - {"route"} != set(patterns) | {"profile"}
        or not isinstance(config.get("profile"), str)
        or not config["profile"].strip()
    ):
        raise ValueError("Check the proxy configuration fields.")

    for key, pattern in patterns.items():
        if not isinstance(config[key], str) or not re.fullmatch(pattern, config[key]):
            raise ValueError(f"Check the proxy field {key}.")

    rendered = proxy_files(config)
    files = {
        "/etc/caddy/Caddyfile": rendered["Caddyfile"],
        "/etc/systemd/system/workshop-caddy.service": rendered["service"],
    }
    payload = base64.b64encode(json.dumps(files).encode()).decode()
    version = config["version"]
    url = f"https://github.com/caddyserver/caddy/releases/download/v{version}/caddy_{version}_linux_amd64.tar.gz"
    writer = (
        "import base64,json,pathlib; files=json.loads(base64.b64decode('"
        + payload
        + "')); [(pathlib.Path(p).write_text(s),pathlib.Path(p).chmod(0o644)) for p,s in files.items()]"
    )

    return [
        "set -eu",
        "test ! -e /usr/local/bin/caddy",
        "test ! -e /etc/systemd/system/workshop-caddy.service",
        "test ! -e /etc/caddy/Caddyfile",
        "task_dir=$(mktemp -d /tmp/workshop-proxy.XXXXXX)",
        f'curl --proto "=https" --tlsv1.2 -fsSL --max-time 120 {shlex.quote(url)} -o "$task_dir/caddy.tar.gz"',
        f'printf "%s  %s\\n" {config["sha256"]} "$task_dir/caddy.tar.gz" | sha256sum -c -',
        'tar -xzf "$task_dir/caddy.tar.gz" -C "$task_dir" caddy',
        'install -m 0755 "$task_dir/caddy" /usr/local/bin/caddy',
        "id caddy >/dev/null 2>&1 || useradd --system --home-dir /var/lib/caddy --shell /sbin/nologin caddy",
        "install -d -m 0755 /etc/caddy",
        "install -d -o caddy -g caddy -m 0700 /var/lib/caddy",
        "python3 -c " + shlex.quote(writer),
        "/usr/local/bin/caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile",
        "systemctl daemon-reload",
        "systemctl enable --now workshop-caddy",
        "systemctl is-active workshop-caddy",
    ]


def release_commands(config, mode, expected=None, backup=None):
    """Build a status or update command without credentials or secrets."""

    commands(config)

    if mode == "install":
        return commands(config)

    if mode not in ("status", "update", "rollback"):
        raise ValueError("Choose install, status, update, or rollback.")

    if mode != "status" and (
        not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected)
    ):
        raise ValueError("Provide the server fingerprint reviewed before the change.")

    if mode == "rollback" and (
        not isinstance(backup, str) or not re.fullmatch(r"release-[a-z0-9_]{8}", backup)
    ):
        raise ValueError("Provide the identifier of the backup to restore.")

    request = {
        "mode": mode,
        "config": config,
        "expected": expected,
        "backup": backup,
        "files": proxy_files(config),
    }
    source = base64.b64encode((ROOT / "scripts/proxy_release.py").read_bytes()).decode()
    payload = base64.b64encode(json.dumps(request).encode()).decode()
    runner = f"import base64,sys; sys.argv=['proxy-release','{payload}']; exec(compile(base64.b64decode('{source}'),'proxy-release','exec'))"

    return ["python3 -c " + shlex.quote(runner)]


def verified_session(config):
    """Check the account and host before reading or changing the deployment."""

    commands(config)

    session = boto3.Session(
        profile_name=config["profile"], region_name=config["region"]
    )
    options = Config(
        connect_timeout=3, read_timeout=30, retries={"total_max_attempts": 1}
    )

    if (
        session.client("sts", config=options).get_caller_identity()["Account"]
        != config["account_id"]
    ):
        raise ValueError("The session belongs to another account.")

    reservations = session.client("ec2", config=options).describe_instances(
        InstanceIds=[config["instance_id"]]
    )["Reservations"]
    instance = reservations[0]["Instances"][0]
    tags = {tag["Key"]: tag["Value"] for tag in instance.get("Tags", [])}

    if (
        instance["State"]["Name"] != "running"
        or tags.get("Name") != config["instance_name"]
        or tags.get("ManagedBy") != "Terraform"
    ):
        raise ValueError(
            "The host does not match the expected target or is not running."
        )

    return session.client("ssm", config=options)


def deploy(config, mode="install", expected=None, backup=None):
    """Send one command to the checked host and return its command ID."""

    script = release_commands(config, mode, expected, backup)
    client = verified_session(config)
    result = client.send_command(
        InstanceIds=[config["instance_id"]],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": script, "executionTimeout": ["600"]},
        TimeoutSeconds=60,
        Comment=f"Workshop proxy: {mode}",
    )

    return result["Command"]["CommandId"]


def main():
    """Preview, run or check the command selected through CLI options."""

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--config", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--mode", choices=("install", "status", "update", "rollback"), default="install"
    )
    parser.add_argument("--expected")
    parser.add_argument("--backup")
    parser.add_argument("--result")
    parser.add_argument("--verify", action="store_true")

    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())

    if args.verify:
        if args.apply or args.result:
            parser.error("Do not combine HTTPS verification with other operations.")

        print(json.dumps(verify_https(config)))

        return

    if args.result:
        if args.apply or not re.fullmatch(r"[a-f0-9-]{36}", args.result):
            parser.error("Query a valid command ID without --apply.")

        response = verified_session(config).get_command_invocation(
            CommandId=args.result, InstanceId=config["instance_id"]
        )

        print(
            json.dumps(
                {
                    key: response.get(key)
                    for key in (
                        "Status",
                        "ResponseCode",
                        "StandardOutputContent",
                        "StandardErrorContent",
                    )
                },
                ensure_ascii=False,
            )
        )

        if response.get("Status") != "Success" or response.get("ResponseCode") != 0:
            raise SystemExit(
                2
                if response.get("Status")
                in ("Pending", "InProgress", "Delayed", "Cancelling")
                else 1
            )

        return

    script = release_commands(config, args.mode, args.expected, args.backup)

    if args.apply:
        print(
            json.dumps(
                {"command_id": deploy(config, args.mode, args.expected, args.backup)}
            )
        )
    else:
        print(
            json.dumps(
                {
                    "mode": args.mode,
                    "instance_id": config["instance_id"],
                    "domain": config["domain"],
                    "route": config.get("route", "maintenance"),
                    "version": config["version"],
                    "expected": args.expected,
                    "backup": args.backup,
                    "command_sha256": hashlib.sha256(
                        "\n".join(script).encode()
                    ).hexdigest(),
                },
                indent=2,
            )
        )


def verify_https(config):
    """Check the public response and redirect with TLS verification and no redirects followed."""

    commands(config)

    login = config.get("route", "maintenance") == "login"
    checks = [(http.client.HTTPSConnection, "/", 200 if login else 503)]

    if login:
        checks.append((http.client.HTTPSConnection, "/_stcore/health", 200))

    checks.append((http.client.HTTPConnection, "/", 308))

    for factory, path, expected in checks:
        connection = factory(config["domain"], timeout=15)

        try:
            connection.request("GET", path)

            response = connection.getresponse()
            body = response.read(4096)

            if response.status != expected:
                raise RuntimeError(
                    "The public response does not match the configured route."
                )

            cache_directives = {
                item.strip().lower()
                for item in (response.getheader("Cache-Control") or "").split(",")
            }

            if expected != 308 and "no-store" not in cache_directives:
                raise RuntimeError("The public response must disable caching.")

            if expected == 200 and (
                (path == "/" and b"<title>Streamlit</title>" not in body)
                or (path == "/_stcore/health" and body != b"ok")
            ):
                raise RuntimeError(
                    "The login service did not return its expected content."
                )

            if expected == 503 and (
                body.decode() != "El taller está en preparación."
                or response.getheader("Cache-Control") != "no-store"
            ):
                raise RuntimeError(
                    "The HTTPS content does not match the expected maintenance response."
                )

            if (
                expected == 308
                and response.getheader("Location") != f"https://{config['domain']}/"
            ):
                raise RuntimeError("The redirect points to an unexpected destination.")
        finally:
            connection.close()

    return {"https": "verified", "domain": config["domain"]}


if __name__ == "__main__":
    main()

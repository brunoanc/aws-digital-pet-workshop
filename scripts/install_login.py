"""Install the login for the first time without changing the public proxy."""

import base64
import fcntl
import gzip
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import time
import urllib.request


def run(command, timeout=120):
    """Run an install command with a timeout and stop if it fails."""

    subprocess.run(command, check=True, timeout=timeout)


def install(bundle):
    """Create the first release and start the login on loopback only."""

    root = Path("/opt/workshop-login")
    config = Path("/etc/workshop-login")
    service = Path("/etc/systemd/system/workshop-login.service")

    if os.geteuid() != 0 or any(
        path.exists() or path.is_symlink() for path in (root, config, service)
    ):
        raise ValueError("First installation requires root and absent login paths.")

    run(["dnf", "-y", "install", "python3.13", "python3.13-pip"], timeout=300)

    try:
        pwd.getpwnam("workshop-login")
    except KeyError:
        run(
            [
                "useradd",
                "--system",
                "--home-dir",
                "/nonexistent",
                "--shell",
                "/sbin/nologin",
                "workshop-login",
            ]
        )

    group = pwd.getpwnam("workshop-login").pw_gid

    root.mkdir(mode=0o755)
    config.mkdir(mode=0o750)
    os.chown(config, 0, group)

    for relative, content in bundle["files"].items():
        path = root / relative

        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("The bundle contains an unsupported file path.")

        path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        path.write_text(content, encoding="utf-8")
        path.chmod(0o644)

    for name in ("runtime", "access"):
        path = config / f"{name}.json"

        path.write_text(json.dumps(bundle[name]), encoding="utf-8")
        path.chmod(0o640)
        os.chown(path, 0, group)

    run(["python3.13", "-m", "venv", str(root / "venv")])
    run(
        [
            str(root / "venv/bin/python"),
            "-m",
            "pip",
            "--isolated",
            "install",
            "--index-url",
            "https://pypi.org/simple",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--require-hashes",
            "--only-binary=:all:",
            "-r",
            str(root / "requirements.txt"),
        ],
        timeout=600,
    )
    run([str(root / "venv/bin/python"), "-m", "pip", "check"])

    service.write_text(bundle["service"], encoding="utf-8")
    service.chmod(0o644)
    run(["systemd-analyze", "verify", str(service)])
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", "workshop-login"])

    for attempt in range(20):
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8501/_stcore/health", timeout=2
            ) as response:
                if response.status == 200 and response.read(32) == b"ok":
                    print(
                        json.dumps(
                            {"status": "healthy", "scope": "loopback-login-only"}
                        )
                    )

                    return
        except OSError:
            pass

        time.sleep(1)

    run(["systemctl", "stop", "workshop-login"])

    raise RuntimeError(
        "Login failed its health check and was stopped; the proxy was not changed."
    )


def main():
    """Lock the installer and install one compressed login bundle."""

    bundle = json.loads(gzip.decompress(base64.b64decode(sys.argv[1])))

    with open("/run/workshop-login-install.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        install(bundle)


if __name__ == "__main__":
    main()

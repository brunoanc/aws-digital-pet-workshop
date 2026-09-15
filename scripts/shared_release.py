"""Update the shared app and keep a backup of the previous service setup."""

import base64
import fcntl
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request


def restart():
    """Restart the service and check its local health endpoint."""

    for command in (
        ["systemctl", "daemon-reload"],
        ["systemctl", "reset-failed", "workshop-login"],
        ["systemctl", "restart", "workshop-login"],
        ["systemctl", "is-active", "--quiet", "workshop-login"],
    ):
        subprocess.run(command, check=True, timeout=30)

    for attempt in range(20):
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8501/_stcore/health", timeout=2
            ) as response:
                if response.status == 200 and response.read(32) == b"ok":
                    return
        except OSError:
            pass

        time.sleep(1)

    raise RuntimeError("The login service did not become healthy.")


def stage(bundle, directory):
    """Create a separate release and check imports before switching the service."""

    for name, content in bundle["files"].items():
        relative = Path(name)

        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.parts[0] not in ("app", "scripts", ".streamlit")
        ):
            raise ValueError("The release contains an unsupported path.")

        target = directory / relative

        target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        target.write_text(content)
        target.chmod(0o644)

    targets = directory / "targets.json"

    targets.write_text(json.dumps(bundle["targets"]))
    targets.chmod(0o644)
    directory.chmod(0o755)

    interpreter = "/opt/workshop-login/venv/bin/python"

    subprocess.run(
        [
            "runuser",
            "-u",
            "workshop-login",
            "--",
            "env",
            "PYTHONDONTWRITEBYTECODE=1",
            interpreter,
            "-c",
            "import app.shared_ui; from app.shared_card import load_targets; load_targets('targets.json')",
        ],
        cwd=directory,
        check=True,
        timeout=30,
    )

    unit = bundle["service"].replace(
        "WorkingDirectory=/opt/workshop-login", f"WorkingDirectory={directory}"
    )
    unit = unit.replace(
        "Environment=PYTHONDONTWRITEBYTECODE=1",
        f"Environment=PYTHONDONTWRITEBYTECODE=1\nEnvironment=PET_UI_ENTRY=app/shared_ui.py\nEnvironment=PET_CARD_CONFIG={targets}",
    )

    return unit


def main():
    """Check the service hash and switch releases with recovery if startup fails."""

    bundle = json.loads(gzip.decompress(base64.b64decode(sys.argv[1])))
    helper = {"__name__": "release_helpers"}

    exec(bundle["helper"], helper)

    helper["FILES"] = {"service": "etc/systemd/system/workshop-login.service"}
    root = Path("/")

    if bundle["mode"] == "status":
        print(json.dumps(helper["snapshot"](root)))

        return

    if os.geteuid() != 0:
        raise PermissionError("Updating the login requires administrator privileges.")

    with open("/run/workshop-login-release.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

        if helper["snapshot"](root)["fingerprint"] != bundle["expected"]:
            raise ValueError("The login service changed after review.")

        with tempfile.TemporaryDirectory(prefix="login-unit-") as temporary:
            staged = Path(temporary)

            if bundle["mode"] == "rollback":
                if not re.fullmatch(r"release-[a-z0-9_]{8}", bundle["backup"]):
                    raise ValueError("Provide a valid login backup identifier.")

                backup = Path("/var/lib/workshop-login-backups") / bundle["backup"]

                helper["verify_backup"](backup)
                shutil.copy2(backup / "service", staged / "service")
            else:
                releases = Path("/opt/workshop-login-releases")

                releases.mkdir(exist_ok=True, mode=0o755)

                directory = Path(tempfile.mkdtemp(prefix="release-", dir=releases))

                (staged / "service").write_text(stage(bundle, directory))

            (staged / "service").chmod(0o644)
            shutil.copy2(staged / "service", staged / "workshop-login.service")
            subprocess.run(
                ["systemd-analyze", "verify", str(staged / "workshop-login.service")],
                check=True,
                timeout=30,
            )

            result = helper["activate"](
                root,
                staged,
                bundle["expected"],
                restart_service=restart,
                archive_path="var/lib/workshop-login-backups",
            )

            print(json.dumps(result))


if __name__ == "__main__":
    main()

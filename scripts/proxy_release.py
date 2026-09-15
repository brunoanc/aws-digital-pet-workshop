"""Update proxy files with a lock, checked backups and recovery on failure."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


FILES = {
    "caddy": "usr/local/bin/caddy",
    "Caddyfile": "etc/caddy/Caddyfile",
    "service": "etc/systemd/system/workshop-caddy.service",
}


def snapshot(root):
    """Hash the three managed files without reading certificates or secrets."""

    hashes = {}

    for name, relative in FILES.items():
        path = root / relative

        if path.is_symlink() or not path.is_file():
            raise ValueError(
                "A managed file is missing or was replaced by a symbolic link."
            )

        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()

    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()

    return {"fingerprint": digest, "files": hashes}


def copy_files(sources, destinations):
    """Replace each file using a temporary copy in the same directory."""

    for name in FILES:
        target = destinations[name]
        descriptor, temporary = tempfile.mkstemp(prefix=".workshop-", dir=target.parent)

        os.close(descriptor)

        try:
            shutil.copy2(sources[name], temporary)
            os.replace(temporary, target)
        finally:
            if Path(temporary).exists():
                Path(temporary).unlink()


def restart():
    """Reload systemd, restart the proxy and check that it is active."""

    for command in (
        ["systemctl", "daemon-reload"],
        ["systemctl", "restart", "workshop-caddy"],
        ["systemctl", "is-active", "--quiet", "workshop-caddy"],
    ):
        subprocess.run(command, check=True, timeout=30)


def activate(
    root,
    staged,
    expected,
    restart_service=restart,
    archive_path="var/lib/workshop-proxy-backups",
):
    """Reject changes since review and restore the backup if startup fails."""

    before = snapshot(root)

    if before["fingerprint"] != expected:
        raise ValueError("The server changed since review, so query its state again.")

    targets = {name: root / relative for name, relative in FILES.items()}
    sources = {name: staged / name for name in FILES}

    if all(
        hashlib.sha256(path.read_bytes()).hexdigest() == before["files"][name]
        for name, path in sources.items()
    ):
        return {"status": "unchanged", **before}

    archive = root / archive_path

    archive.mkdir(parents=True, exist_ok=True, mode=0o700)

    backup = Path(tempfile.mkdtemp(prefix="release-", dir=archive))

    for name, path in targets.items():
        shutil.copy2(path, backup / name)

    (backup / "manifest.json").write_text(json.dumps(before, sort_keys=True))
    print(json.dumps({"backup": backup.name}), flush=True)

    try:
        copy_files(sources, targets)
        restart_service()
    except Exception as failure:
        try:
            copy_files({name: backup / name for name in FILES}, targets)
            restart_service()
        except Exception as recovery:
            raise RuntimeError(
                f"Recovery failed; keep backup {backup.name} and check SSM."
            ) from recovery

        raise RuntimeError(
            f"Startup failed and backup {backup.name} was restored; check the service before retrying."
        ) from failure

    return {"status": "updated", "backup": backup.name, **snapshot(root)}


def verify_backup(backup):
    """Check backup hashes before restoring its files."""

    manifest = json.loads((backup / "manifest.json").read_text())

    for name in FILES:
        path = backup / name

        if (
            path.is_symlink()
            or hashlib.sha256(path.read_bytes()).hexdigest() != manifest["files"][name]
        ):
            raise ValueError("The backup does not match its manifest.")


def main():
    """Run status, update or rollback on fixed paths with a lock for changes."""

    import base64
    import fcntl
    import re
    import sys
    import tarfile
    import urllib.request

    request = json.loads(base64.b64decode(sys.argv[1]))
    root = Path("/")

    if request["mode"] == "status":
        print(json.dumps(snapshot(root)))

        return

    if os.geteuid() != 0:
        raise PermissionError("Updating requires host administrator privileges.")

    with open("/run/workshop-proxy-deploy.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

        if snapshot(root)["fingerprint"] != request["expected"]:
            raise ValueError("The server changed since review.")

        with tempfile.TemporaryDirectory(prefix="workshop-release-") as directory:
            staged = Path(directory)

            if request["mode"] == "rollback":
                if not re.fullmatch(r"release-[a-z0-9_]{8}", request["backup"]):
                    raise ValueError("Specify a valid backup identifier.")

                backup = root / "var/lib/workshop-proxy-backups" / request["backup"]

                verify_backup(backup)

                for name in FILES:
                    shutil.copy2(backup / name, staged / name)
            elif request["mode"] == "update":
                config = request["config"]
                version = config["version"]
                url = f"https://github.com/caddyserver/caddy/releases/download/v{version}/caddy_{version}_linux_amd64.tar.gz"
                archive = staged / "download.tar.gz"

                with (
                    urllib.request.urlopen(url, timeout=120) as response,
                    archive.open("wb") as destination,
                ):
                    shutil.copyfileobj(response, destination)

                if hashlib.sha256(archive.read_bytes()).hexdigest() != config["sha256"]:
                    raise ValueError("The download does not match the expected hash.")

                with tarfile.open(archive) as bundle:
                    member = bundle.getmember("caddy")

                    if not member.isfile():
                        raise ValueError("The downloaded binary is not a regular file.")

                    with (
                        bundle.extractfile(member) as source,
                        (staged / "caddy").open("wb") as destination,
                    ):
                        shutil.copyfileobj(source, destination)

                (staged / "caddy").chmod(0o755)

                for name in ("Caddyfile", "service"):
                    (staged / name).write_text(request["files"][name])
                    (staged / name).chmod(0o644)
            else:
                raise ValueError("The operation is unknown.")

            subprocess.run(
                [
                    str(staged / "caddy"),
                    "validate",
                    "--config",
                    str(staged / "Caddyfile"),
                    "--adapter",
                    "caddyfile",
                ],
                check=True,
                timeout=30,
            )

            unit = staged / "workshop-caddy.service"

            shutil.copy2(staged / "service", unit)
            subprocess.run(
                ["systemd-analyze", "verify", str(unit)], check=True, timeout=30
            )

            result = activate(root, staged, request["expected"])

            print(json.dumps(result))


if __name__ == "__main__":
    main()

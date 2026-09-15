"""Build a Lambda dependency layer locally without deploying it."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile


def build(requirements, output):
    """Check package hashes and build a Linux layer ZIP with a report."""

    requirements = Path(requirements).resolve(strict=True)
    output = Path(output).resolve()

    if output.exists():
        raise ValueError(
            "Choose a new output directory to keep the existing files."
        )

    output.mkdir(parents=True)

    dependencies = output / "python"

    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--target",
            str(dependencies),
            "--python-version",
            "3.13",
            "--python-platform",
            "x86_64-manylinux2014",
            "--only-binary",
            ":all:",
            "--require-hashes",
            "-r",
            str(requirements),
        ],
        check=True,
    )

    files = sorted(path for path in dependencies.rglob("*") if path.is_file())
    unpacked = sum(path.stat().st_size for path in files)

    if unpacked >= 250 * 1024 * 1024:
        raise ValueError(
            "Dependencies reach the Lambda size limit and leave no room for code."
        )

    archive = output / "agent-layer.zip"

    with ZipFile(archive, "w", ZIP_DEFLATED) as package:
        for path in files:
            package.write(path, path.relative_to(output))

    report = {
        "runtime": "python3.13",
        "architecture": "x86_64",
        "files": len(files),
        "uncompressed_bytes": unpacked,
        "compressed_bytes": archive.stat().st_size,
        "requirements_sha256": hashlib.sha256(requirements.read_bytes()).hexdigest(),
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }

    (output / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    return report


def main():
    """Build the layer from the supplied paths and print its report."""

    parser = argparse.ArgumentParser(
        description="Package agent dependencies for Lambda."
    )

    parser.add_argument(
        "--requirements",
        required=True,
        help="Provide the hash-pinned requirements file.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Provide a new directory for the layer and its report.",
    )

    args = parser.parse_args()

    print(json.dumps(build(args.requirements, args.output), indent=2))


if __name__ == "__main__":
    main()

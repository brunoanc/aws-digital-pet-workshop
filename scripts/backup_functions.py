"""Back up Lambda code and settings without changing AWS resources."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
from urllib.request import urlopen

import boto3
from botocore.config import Config


def backup(account, profile, region, functions, output):
    """Check the account and save verified Lambda ZIPs in a new directory."""

    if (
        not re.fullmatch(r"[0-9]{12}", account)
        or not functions
        or len(set(functions)) != len(functions)
    ):
        raise ValueError("Specify a valid account and unique functions.")

    for name in functions:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,63}", name):
            raise ValueError("Specify valid function names rather than paths or ARNs.")

    session = boto3.Session(profile_name=profile, region_name=region)
    config = Config(
        connect_timeout=3, read_timeout=30, retries={"total_max_attempts": 1}
    )

    if session.client("sts", config=config).get_caller_identity()["Account"] != account:
        raise ValueError(
            "Wrong AWS account; no code was downloaded."
        )

    destination = Path(output)

    destination.mkdir(mode=0o700, parents=False, exist_ok=False)

    client = session.client("lambda", config=config)
    manifest = {"account_id": account, "region": region, "functions": {}}

    for name in functions:
        arn = f"arn:{session.get_partition_for_region(region)}:lambda:{region}:{account}:function:{name}"
        response = client.get_function(FunctionName=arn)
        configuration = response["Configuration"]

        if (
            configuration["FunctionArn"] != arn
            or configuration.get("PackageType") != "Zip"
        ):
            raise ValueError("The function does not match the expected ZIP target.")

        with urlopen(response["Code"]["Location"], timeout=30) as download:
            package = download.read(50 * 1024 * 1024 + 1)

        digest = base64.b64encode(hashlib.sha256(package).digest()).decode()

        if len(package) > 50 * 1024 * 1024 or digest != configuration["CodeSha256"]:
            raise ValueError(
                "The downloaded package does not match the published hash."
            )

        current = client.get_function_configuration(FunctionName=arn)

        if current["RevisionId"] != configuration["RevisionId"]:
            raise ValueError(
                "The function changed during backup; try again with a new directory."
            )

        (destination / f"{name}.zip").write_bytes(package)
        (destination / f"{name}.json").write_text(
            json.dumps(configuration, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        manifest["functions"][name] = {
            "code_sha256": digest,
            "revision_id": configuration["RevisionId"],
        }

    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    return manifest


def main():
    """Back up the selected functions and print their hashes and revision IDs."""

    parser = argparse.ArgumentParser(description=__doc__)

    for name in ("account", "profile", "region", "output"):
        parser.add_argument("--" + name, required=True)

    parser.add_argument("--functions", nargs="+", required=True)

    args = parser.parse_args()

    try:
        manifest = backup(
            args.account, args.profile, args.region, args.functions, args.output
        )
    except Exception:
        raise SystemExit(
            "Backup failed; keep partial downloads and check SSO, permissions, and targets."
        ) from None

    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()

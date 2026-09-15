"""Generate private capacity configurations without changing AWS resources."""

import argparse
import json
import os
from pathlib import Path
import re

from scripts.capacity_plan import build_plan


ROOT = Path(__file__).resolve().parents[1]


def render_files(config, deployment, output):
    """Build separate backend and variable files with absolute source paths."""

    plan = build_plan(config)
    output = Path(output).resolve()
    backend = deployment["backend"]

    if (
        set(backend)
        != {
            "bucket",
            "region",
            "profile",
            "allowed_account_ids",
            "encrypt",
            "use_lockfile",
        }
        or backend["allowed_account_ids"] != [config["management_account_id"]]
        or backend["encrypt"] is not True
        or backend["use_lockfile"] is not True
        or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", backend["bucket"])
        or not isinstance(backend["profile"], str)
        or not backend["profile"].strip()
        or not re.fullmatch(r"[a-z]{2}(-[a-z]+)+-[0-9]+", backend["region"])
    ):
        raise ValueError(
            "Use an encrypted management backend with locking and no existing key."
        )

    if (
        deployment["agent_memory_mb"] not in (512, 1024)
        or type(deployment["agent_timeout_seconds"]) is not int
        or not config["timeout_seconds"] + 10
        <= deployment["agent_timeout_seconds"]
        <= 150
        or deployment["pet_memory_mb"] not in (128, 256, 512)
        or type(deployment["pet_timeout_seconds"]) is not int
        or not 5 <= deployment["pet_timeout_seconds"] <= 30
        or deployment["log_retention_days"] not in (1, 3, 5, 7, 14)
    ):
        raise ValueError("Use supported memory, timeouts and log retention.")

    layer = (ROOT / deployment["layer_zip_path"]).resolve()
    builder = (ROOT / plan["builder_source"]).resolve()

    if not layer.is_file() or not builder.is_file():
        raise ValueError(
            "Build the dependency layer and capacity builder before generating files."
        )

    files = {}
    manifest = {
        "account_id": config["account_id"],
        "region": config["region"],
        "stacks": [],
    }

    def add_stack(name, root, key, variables):
        """Render one stack with its own backend key and Terraform data directory."""

        backend_name = name + ".tfbackend"
        variables_name = name + ".tfvars.json"
        files[backend_name] = (
            "\n".join(
                f"{field} = {json.dumps(value)}"
                for field, value in (backend | {"key": key}).items()
            )
            + "\n"
        )
        files[variables_name] = json.dumps(variables, indent=2) + "\n"

        manifest["stacks"].append(
            {
                "name": name,
                "root": str(ROOT / root),
                "backend": str(output / backend_name),
                "variables": str(output / variables_name),
                "state_key": key,
                "tf_data_dir": str(output / "terraform-data" / name),
            }
        )

    common = {
        "account_id": config["account_id"],
        "management_account_id": config["management_account_id"],
        "aws_profile": config["profile"],
        "region": config["region"],
        "log_retention_days": deployment["log_retention_days"],
        "tags": deployment["tags"],
    }

    add_stack(
        "pets",
        "infra/pets",
        plan["pet_state_key"],
        {
            "workload": common
            | {
                "teams": {
                    team: target["runtime"]["function_name"]
                    for team, target in plan["teams"].items()
                },
                "read_only": True,
                "runtime": "python3.13",
                "memory_mb": deployment["pet_memory_mb"],
                "timeout_seconds": deployment["pet_timeout_seconds"],
            }
        },
    )

    for team, target in plan["teams"].items():
        runtime_name = team + ".runtime.json"
        files[runtime_name] = (
            json.dumps(target["runtime"], indent=2, ensure_ascii=False) + "\n"
        )

        add_stack(
            team,
            "infra/agent",
            target["agent_state_key"],
            {
                "agent": common
                | {
                    "function_name": target["agent_function"],
                    "layer_name": target["agent_function"] + "-deps",
                    "layer_zip_path": str(layer),
                    "runtime_config_path": str(output / runtime_name),
                    "builder_source_path": os.path.relpath(
                        builder, ROOT / "infra/agent"
                    ),
                    "memory_mb": deployment["agent_memory_mb"],
                    "timeout_seconds": deployment["agent_timeout_seconds"],
                    "function_url_enabled": True,
                }
            },
        )

    files["manifest.json"] = json.dumps(manifest, indent=2) + "\n"

    return files


def write_new_files(files, output):
    """Write a private directory exclusively and leave partial output for inspection on failure."""

    output = Path(output)

    output.mkdir(mode=0o700, parents=False, exist_ok=False)

    for name, content in files.items():
        if Path(name).name != name or name in (".", ".."):
            raise ValueError("Use flat filenames inside the new capacity directory.")

        with (output / name).open("x", encoding="utf-8") as stream:
            (output / name).chmod(0o600)
            stream.write(content)


def main():
    """Preview filenames or create a new private directory only with explicit write intent."""

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--config", required=True)
    parser.add_argument("--deployment", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--write", action="store_true")

    args = parser.parse_args()
    files = render_files(
        json.loads(Path(args.config).read_text()),
        json.loads(Path(args.deployment).read_text()),
        args.output,
    )

    if args.write:
        write_new_files(files, args.output)

    print(json.dumps({"written": args.write, "files": sorted(files)}))


if __name__ == "__main__":
    main()

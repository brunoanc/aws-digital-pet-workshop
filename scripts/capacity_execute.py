"""Preview or explicitly run one capacity pass after checking deployed resources."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from scripts.capacity_aws import CapacityAWS
from scripts.capacity_plan import build_plan
from scripts.capacity_runner import run_batches


def approval_hash(config, expected):
    """Bind execution approval to the exact configuration and reviewed deployment hashes."""

    return hashlib.sha256(
        json.dumps({"config": config, "expected": expected}, sort_keys=True).encode()
    ).hexdigest()


def save_report(path, report):
    """Create a private report without replacing an existing result."""

    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)

    with os.fdopen(descriptor, "w") as stream:
        json.dump(report, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def execute(config, expected, output, transport_factory=CapacityAWS):
    """Run one non-resumable pass and check unchanged state after every batch."""

    plan = build_plan(config)
    output = Path(output)

    output.mkdir(mode=0o700, parents=False, exist_ok=False)

    report = {
        "status": "preflight",
        "approval_sha256": approval_hash(config, expected),
        "batches": [],
    }

    save_report(output / "started.json", report)

    transport = transport_factory(config, plan, expected)

    try:
        transport.preflight()

        before = transport.snapshot()

        save_report(output / "before.json", before)

        def after_batch(records):
            """Save each completed batch and stop if any synthetic pet changed."""

            report["batches"] = records
            current = transport.snapshot()
            unchanged = before == current

            save_report(
                output / f"batch-{len(records)}.json",
                {"batch": records[-1], "unchanged": unchanged},
            )

            if not unchanged:
                raise ValueError(
                    "Pet state changed during the read-only test, so no further batches will run."
                )

        records = run_batches(plan, transport.invoke, after_batch=after_batch)
        report["batches"] = records
        report["status"] = (
            "passed"
            if len(records) == 4
            and all(item["success"] for batch in records for item in batch["results"])
            else "failed"
        )
    except Exception as error:
        report["status"] = "failed"
        report["error"] = type(error).__name__

        raise
    finally:
        save_report(output / "result.json", report)

    return report


def main():
    """Require a matching approval hash before sending any model requests."""

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("--config", required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approved-sha256")
    parser.add_argument("--output")

    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    expected = json.loads(Path(args.expected).read_text())
    plan = build_plan(config)
    digest = approval_hash(config, expected)

    if args.preflight and args.execute:
        parser.error("Choose preflight or execution, not both.")

    if args.execute:
        if args.approved_sha256 != digest or not args.output:
            parser.error(
                "Supply the reviewed approval hash and a new output directory."
            )

        report = execute(config, expected, args.output)

        print(json.dumps(report))

        if report["status"] != "passed":
            raise SystemExit(1)
    elif args.preflight:
        transport = CapacityAWS(config, plan, expected)

        transport.preflight()
        transport.snapshot()
        print(json.dumps({"status": "preflight-passed", "inferences": 0}))
    else:
        print(
            json.dumps(
                {
                    "mode": "plan",
                    "approval_sha256": digest,
                    "max_requests": plan["max_requests"],
                    "inferences": 0,
                }
            )
        )


if __name__ == "__main__":
    main()

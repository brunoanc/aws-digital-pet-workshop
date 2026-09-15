"""Run bounded inspection batches using an explicitly supplied transport."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import time


def validate_result(result, team):
    """Require successful inspection evidence for the expected team."""

    activity = result.get("activity", [])

    if (
        result.get("success") is not True
        or result.get("registered_tools") != ["inspect_pet"]
        or not activity
        or any(
            event.get("tool") != "inspect_pet"
            or event.get("action") != "inspect"
            or event.get("result", {}).get("success") is not True
            or event.get("result", {}).get("pet", {}).get("pet_id") != team
            for event in activity
        )
    ):
        raise ValueError("The response lacks valid read-only evidence for this team.")


def run_batches(plan, invoke, wait=time.sleep, after_batch=None):
    """Stop after a failed batch without retrying or cancelling in-flight calls."""

    if (
        [len(batch) for batch in plan["batches"]] != [2, 5, 10, 15]
        or plan["pause_seconds"] < 60
        or plan["read_only"] is not True
        or plan["max_requests"] != 32
        or any(
            len(set(batch)) != len(batch)
            or any(
                team not in {f"team-{number}" for number in range(81, 96)}
                for team in batch
            )
            for batch in plan["batches"]
        )
    ):
        raise ValueError("Use the reviewed capacity batch sizes.")

    records = []

    def measure(team):
        """Measure one request and retain failures without exposing response contents."""

        start = time.monotonic()

        try:
            validate_result(invoke(team, plan["message"]), team)
        except Exception as error:
            return {
                "team": team,
                "success": False,
                "error": type(error).__name__,
                "seconds": time.monotonic() - start,
            }

        return {"team": team, "success": True, "seconds": time.monotonic() - start}

    for index, batch in enumerate(plan["batches"]):
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = [pool.submit(measure, team) for team in batch]
            results = [future.result() for future in as_completed(futures)]

        records.append({"batch": index + 1, "results": results})

        if after_batch is not None:
            after_batch(records)

        if not all(result["success"] for result in results):
            break

        if index + 1 < len(plan["batches"]):
            wait(plan["pause_seconds"])

    return records

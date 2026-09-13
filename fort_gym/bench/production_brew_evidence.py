"""Correlate retained fixture identities; never infer total production or coverage."""

from __future__ import annotations

from .production_brew_fixture import REACTION, SCHEMA as QUEUE_SCHEMA

SCHEMA = "fortgym.private-production-brew-evidence/v1"


def _integer(value: object) -> bool:
    return type(value) is int and 0 <= value <= 9007199254740991


def _inventory(value: dict) -> dict[int, dict]:
    items = value.get("items")
    if not isinstance(items, list) or len(items) > 8192:
        raise ValueError("Brew evidence requires bounded retained inventories")
    indexed = {}
    for item in items:
        if not isinstance(item, dict) or not _integer(item.get("item_id")):
            raise ValueError("Invalid inventory item identity")
        if item["item_id"] in indexed:
            raise ValueError("Duplicate inventory item identity")
        indexed[item["item_id"]] = item
    return indexed


def summarize_brew_evidence(queued: dict, baseline: dict, endpoint: dict) -> dict:
    """Match one inserted job with read-only callback fields and retain overlaps.

    Callers first validate the queue receipt and each complete paused boundary.
    This function additionally checks shared ownership and cumulative retention.
    A match is corroboration to inspect in a real fixture, not native acceptance.
    """
    ids = queued.get("created_job_ids")
    if (
        queued.get("schema_version") != QUEUE_SCHEMA
        or queued.get("ok") is not True
        or queued.get("command_mutation") != "completed"
        or queued.get("reaction_code") != REACTION
        or type(queued.get("quantity")) is not int
        or queued["quantity"] != 1
        or type(queued.get("jobs_queued")) is not int
        or queued["jobs_queued"] != 1
        or type(queued.get("queue_before")) is not int
        or queued["queue_before"] != 0
        or type(queued.get("queue_after")) is not int
        or queued["queue_after"] != 1
        or not _integer(queued.get("workshop_id"))
        or not isinstance(ids, list)
        or len(ids) != 1
        or not _integer(ids[0])
        or not isinstance(queued.get("owner"), str)
        or not queued["owner"]
    ):
        raise ValueError("Brew evidence requires a confirmed single-job insertion")
    for snapshot in (baseline, endpoint):
        events, inventory = snapshot.get("events", {}), snapshot.get("inventory", {})
        if (
            snapshot.get("owner") != queued["owner"]
            or events.get("campaign_id") != queued["owner"]
            or inventory.get("campaign_id") != queued["owner"]
            or events.get("collector_records_complete") is not True
            or inventory.get("complete") is not True
            or events.get("native_coverage_validated") is not False
        ):
            raise ValueError("Brew evidence ownership or completeness differs")
        retained = events.get("events")
        if (
            not isinstance(retained, list)
            or len(retained) > 256
            or type(events.get("observed_events")) is not int
            or events["observed_events"] != len(retained)
        ):
            raise ValueError("Brew event retention is incomplete or over limit")
        for index, event in enumerate(retained, 1):
            if (
                not isinstance(event, dict)
                or type(event.get("sequence")) is not int
                or event["sequence"] != index
            ):
                raise ValueError("Brew event sequence is discontinuous")
    initial, final = baseline["events"], endpoint["events"]
    point = baseline["inventory"].get("start", {})
    insertion_boundary = {
        key: point.get(key) for key in ("root", "year", "year_tick", "save_name")
    }
    insertion_boundary["paused"] = True
    if (
        queued.get("before") != insertion_boundary
        or queued.get("after") != insertion_boundary
    ):
        raise ValueError("Brew insertion and baseline boundaries differ")
    if (
        initial.get("start") != final.get("start")
        or final["events"][: len(initial["events"])] != initial["events"]
    ):
        raise ValueError("Brew observer origin or event prefix differs")
    before_items, after_items = (
        _inventory(baseline["inventory"]),
        _inventory(endpoint["inventory"]),
    )
    job_id, workshop_id = ids[0], queued["workshop_id"]
    matches, unmatched, completions = [], [], []
    observations: dict[int, dict] = {}
    for event in final["events"][len(initial["events"]) :]:
        if event.get("kind") == "job_completion_notification":
            if type(event.get("job_id")) is int and event["job_id"] == job_id:
                completions.append(event["sequence"])
            continue
        if (
            event.get("kind") != "reaction_output_observation"
            or event.get("reaction_code") != REACTION
        ):
            continue
        context = event.get("worker_job", {})
        if not isinstance(context, dict):
            raise ValueError("Invalid worker job context")
        matched = (
            context.get("status") == "observed"
            and type(context.get("job_id")) is int
            and context["job_id"] == job_id
            and context.get("job_type") == "CustomReaction"
            and context.get("reaction_name") == REACTION
            and type(context.get("building_holder_id")) is int
            and context["building_holder_id"] == workshop_id
            and _integer(event.get("worker_id"))
            and type(context.get("assigned_worker_id")) is int
            and context["assigned_worker_id"] == event["worker_id"]
        )
        if not matched:
            unmatched.append(event["sequence"])
            continue
        outputs = event.get("output_items")
        if (
            event.get("vector_scope") != "cumulative_outputs_at_callback"
            or not isinstance(outputs, list)
            or not 1 <= len(outputs) <= 32
        ):
            raise ValueError("Brew output vector is missing or over limit")
        matches.append(event["sequence"])
        for item in outputs:
            if (
                not isinstance(item, dict)
                or not _integer(item.get("item_id"))
                or not _integer(item.get("units_at_observation"))
                or item.get("resource") not in ("drink", "food", "other")
            ):
                raise ValueError("Invalid brew output item observation")
            item_id = item["item_id"]
            record = observations.setdefault(
                item_id,
                {
                    "item_id": item_id,
                    "present_in_baseline_inventory": item_id in before_items,
                    "present_in_endpoint_inventory": item_id in after_items,
                    "observations": [],
                },
            )
            record["observations"].append(
                {
                    "event_sequence": event["sequence"],
                    "worker_id": event["worker_id"],
                    "resource": item["resource"],
                    "units_at_observation": item["units_at_observation"],
                }
            )
    return {
        "schema_version": SCHEMA,
        "owner": queued["owner"],
        "job_id": job_id,
        "workshop_id": workshop_id,
        "reaction_code": REACTION,
        "matching_reaction_sequences": matches,
        "unmatched_brewing_sequences": unmatched,
        "job_completion_notification_sequences": completions,
        "output_item_observations": list(observations.values()),
        "matching_native_fields_observed": bool(matches),
        "native_binding_validated": False,
        "independent_production_oracle": False,
        "production_quantity": None,
        "production_coverage": "inconclusive",
        "inventory_absence_is_not_loss_or_consumption": True,
    }

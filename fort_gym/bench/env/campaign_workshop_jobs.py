"""Runtime-bound selected-workshop shorthand; no implicit keys or retries."""

from pathlib import Path

from ..dfhack_backend import _hook_path
from ..dfhack_exec import DFHackError, run_lua_file
from .campaign_binding_keys import read_binding_index
from .campaign_keyboard import execute_campaign_keys
from .native_key_catalog import NATIVE_PROFILE
from .workshop_job_profile import ITEMS, MAX_QUANTITY, RECEIPT_SCHEMA


def execute_workshop_job(
    params: object, *, expected_dfroot: Path, year: object, year_tick: object
) -> dict:
    result = {
        "schema_version": "fortgym.campaign-workshop-input/v1",
        "action_route": "selected_workshop_job",
        "ok": False, "command_mutation": "not_attempted",
        "keys_confirmed": 0, "jobs_queued": 0,
    }

    def finish(error: str | None = None) -> dict:
        result["ok"] = error is None
        if error is not None:
            result["error"] = error
        return {"accepted": result["ok"], "why": error, "result": result}

    if (
        not isinstance(params, dict) or set(params) != {"item", "quantity"}
        or not isinstance(params.get("item"), str) or params["item"] not in ITEMS
        or type(params.get("quantity")) is not int
        or not 1 <= params["quantity"] <= MAX_QUANTITY
        or type(year) is not int or year < 0
        or type(year_tick) is not int or not 0 <= year_tick < 403200
    ):
        return finish("Invalid selected-workshop request")
    root = expected_dfroot.resolve()
    try:
        read_binding_index(root)
    except (ValueError, OSError) as error:
        return finish(str(error))
    probe = execute_campaign_keys(
        [], expected_dfroot=root, year=year, year_tick=year_tick, control_profile=NATIVE_PROFILE
    )
    result["boundary_probe"] = probe
    if probe.get("accepted") is not True:
        return finish("Selected-workshop native boundary probe failed")
    save = probe["result"]["native_receipts"][-1]["after"]["save_name"]
    result.update(command_mutation="unknown", jobs_queued=None)
    try:
        receipt = run_lua_file(
            _hook_path("campaign_selected_workshop_job_v1.lua"),
            str(root), str(year), str(year_tick), save,
            params["item"], str(params["quantity"]), timeout=5,
        )
    except (DFHackError, OSError) as error:
        return finish(str(error))
    result["native_receipt"] = receipt
    if not isinstance(receipt, dict) or receipt.get("schema_version") != RECEIPT_SCHEMA:
        return finish("Malformed selected-workshop receipt")
    count = receipt.get("jobs_queued")
    if receipt.get("ok") is False:
        if (receipt.get("command_mutation") == "not_attempted"
                and type(count) is int and count == 0
                and receipt.get("created_job_ids") == []):
            result.update(command_mutation="not_attempted", jobs_queued=0)
        return finish(str(receipt.get("error") or "Selected-workshop job failed"))
    ids = receipt.get("created_job_ids")
    workshop_id = receipt.get("workshop_id")
    queue_before, queue_after = receipt.get("queue_before"), receipt.get("queue_after")
    valid = (
        receipt.get("ok") is True and receipt.get("command_mutation") == "completed"
        and receipt.get("item") == params["item"]
        and type(receipt.get("quantity")) is int and receipt["quantity"] == params["quantity"]
        and type(count) is int and count == params["quantity"]
        and isinstance(ids, list) and len(ids) == count
        and all(type(value) is int and value >= 0 for value in ids)
        and len(set(ids)) == count
        and type(workshop_id) is int and workshop_id >= 0
        and type(queue_before) is int and queue_before >= 0
        and type(queue_after) is int and queue_after == queue_before + count <= 10
    )
    for point in (receipt.get("before"), receipt.get("after")):
        valid = valid and (
            isinstance(point, dict) and point.get("dfroot") == str(root)
            and type(point.get("year")) is int and point["year"] == year
            and type(point.get("year_tick")) is int and point["year_tick"] == year_tick
            and point.get("paused") is True and point.get("save_name") == save
        )
    if not valid:
        return finish("Selected-workshop receipt does not establish the requested jobs and boundary")
    result.update(command_mutation="completed", jobs_queued=count)
    try:
        read_binding_index(root)
    except (ValueError, OSError) as error:
        result["command_mutation"] = "partial"
        return finish(str(error))
    return finish()

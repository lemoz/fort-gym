"""Private RPC adapter for a disposable production-observer fixture, not an agent."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .dfhack_exec import run_lua_expr
from .production_observer_lua import PRODUCTION_OBSERVER_LUA

SLOT = "fortgym_private_production_probe_v1"
SCHEMA = "fortgym.private-production-probe-boundary/v1"


class ProductionObserverProbe:
    """Own exactly one observer slot; never remove another owner's callbacks."""

    def __init__(self, runtime: Path, owner: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{32}", owner):
            raise ValueError("Probe owner must be a unique 32-character hex identity")
        self.runtime = runtime.resolve()
        self.owner = owner

    def expression(self, operation: str) -> str:
        """Build one runtime-bound RPC operation without contacting a game."""
        if operation not in ("start", "capture", "stop"):
            raise ValueError("Unknown observer probe operation")
        prefix = (
            f"local owner = {json.dumps(self.owner)}\n"
            f"local root = {json.dumps(str(self.runtime))}\n"
            "assert(dfhack.getDFPath() == root, 'probe runtime differs')\n"
            f"local slot = rawget(_G, '{SLOT}')\n"
        )
        if operation == "start":
            return (
                prefix
                + PRODUCTION_OBSERVER_LUA
                + f"""
assert(slot == nil, 'probe slot already occupied')
local observer = new_production_observer(df, dfhack, require('plugins.eventful'), {{
    campaign_id=owner, segment_id=0, expected_root=root,
    max_events=256, max_inventory_items=8192,
}})
observer.start()
rawset(_G, '{SLOT}', {{owner=owner, observer=observer}})
print(require('json').encode({{schema_version='{SCHEMA}', owner=owner,
    operation='start', installed=true}}))
"""
            )
        if operation == "stop":
            return (
                prefix
                + f"""
if slot == nil then
    print(require('json').encode({{schema_version='{SCHEMA}', owner=owner,
        operation='stop', installed=false, owner_slot_absent=true}}))
else
    assert(slot.owner == owner, 'probe owner differs')
    slot.observer.stop()
    local events = slot.observer.snapshot()
    rawset(_G, '{SLOT}', nil)
    print(require('json').encode({{schema_version='{SCHEMA}', owner=owner,
        operation='stop', installed=false, events=events}}))
end
"""
            )
        return (
            prefix
            + f"""
assert(slot ~= nil and slot.owner == owner, 'probe owner differs')
local inventory = slot.observer.inventory_snapshot()
local events = slot.observer.snapshot()
print(require('json').encode({{schema_version='{SCHEMA}', owner=owner,
    operation='capture', inventory=inventory, events=events}}))
"""
        )

    def command(self, operation: str) -> dict:
        result = json.loads(run_lua_expr(self.expression(operation), timeout=10))
        if (
            not isinstance(result, dict)
            or result.get("schema_version") != SCHEMA
            or result.get("owner") != self.owner
            or result.get("operation") != operation
        ):
            raise ValueError("Native observer response identity differs")
        return result


def validate_boundary(value: dict, state: dict, runtime: Path, owner: str) -> None:
    """Require complete, same-pause evidence without claiming production coverage."""
    inventory, events = value.get("inventory", {}), value.get("events", {})
    if (
        value.get("schema_version") != SCHEMA
        or value.get("owner") != owner
        or value.get("operation") != "capture"
        or inventory.get("schema_version") != "fortgym.private-production-inventory/v1"
        or events.get("schema_version") != "fortgym.private-production-events/v1"
        or inventory.get("complete") is not True
        or events.get("collector_records_complete") is not True
        or events.get("installed") is not True
        or state.get("pause_state") is not True
    ):
        raise ValueError("Incomplete native observer boundary")
    for snapshot in (inventory, events):
        if (
            snapshot.get("campaign_id") != owner
            or snapshot.get("segment_id") != 0
            or snapshot.get("native_coverage_validated") is not False
            or snapshot.get("agent_observation") is not False
        ):
            raise ValueError("Observer identity or measurement scope differs")
    point = inventory.get("start")
    if (
        not isinstance(point, dict)
        or point != inventory.get("endpoint")
        or point != events.get("endpoint")
        or inventory.get("observer_start") != events.get("start")
        or inventory.get("event_sequence") != events.get("observed_events")
        or point.get("root") != str(runtime.resolve())
        or point.get("save_name") != "campaign-resume"
        or (point.get("year"), point.get("year_tick"))
        != (state.get("year"), state.get("year_tick"))
    ):
        raise ValueError("Observer and native calendar boundaries differ")

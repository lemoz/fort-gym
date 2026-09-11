"""Expose existing inventory provenance without redefining historical raw stocks."""

from ..food_inventory import validate_food_inventory


def stock_context(result: dict) -> dict:
    """Describe the final saved endpoint only, not ownership or production."""
    raw_food, raw_drink = (result["saved_metrics"][key] for key in ("food_stock", "drink_stock"))
    if any(
        value is not None and (type(value) is not int or value < 0)
        for value in (raw_food, raw_drink)
    ):
        raise ValueError("Invalid recorded stock count")
    measurement = result.get("food_measurement")
    if measurement is not None and not isinstance(measurement, dict):
        raise ValueError("Invalid recorded food measurement")
    inventory = (measurement or {}).get("final_inventory")
    status, trader, non_trader = "unavailable", None, None
    if inventory is not None:
        inventory = validate_food_inventory(inventory)
        if inventory["units"] != raw_food:
            raise ValueError("Recorded food inventory differs from saved raw stock")
        status = "complete" if inventory["complete"] else "incomplete"
        if inventory["complete"]:
            trader = inventory["trader_units"]
            non_trader = inventory["units"] - trader
    return {
        "schema_version": "fortgym.recorded-stock-context/v1",
        "scope": "final_checkpoint_only",
        "responses": result["responses"],
        "checkpoint_sha256": result["checkpoint_sha256"],
        "food": {
            "measurement_status": status,
            "raw_units": raw_food,
            "trader_flagged_units": trader,
            "units_without_trader_flag": non_trader,
        },
        "drink": {"raw_units": raw_drink, "trader_flagged_units": None},
        "ownership_and_accessibility_verified": False,
        "production_or_sustainability_verified": False,
    }

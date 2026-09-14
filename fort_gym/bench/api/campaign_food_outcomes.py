"""Public aggregate food measurements, separate from historical unknown stock."""

from __future__ import annotations

PROFILE = "fortgym.campaign-food-measurement/v1"


def food_inventory_outcome(source: dict, decisions: int, parent_cursor: int) -> dict | None:
    """Allowlist independently reviewed counts without item or model content."""
    value = source.get("food_inventory")
    profile = source.get("private_measurement_profile")
    if value is None and profile is None:
        return None
    expected = {
        "schema_version": "fortgym.keyboard-food-inventory-outcome/v1",
        "measurement_profile": PROFILE,
        "independent_private_review_passed": True,
        "historical_food_unknowns_preserved": True,
        "model_requests_remain_screen_only": True,
        "scope": "native_edible_raw_predicate_excluding_drinks",
        "accessibility": "not_assessed",
        "production_and_consumption": "not_measured",
        "sustainability": "not_established",
    }
    if profile != PROFILE or not isinstance(value, dict) or any(
        type(value.get(key)) is not type(target) or value[key] != target
        for key, target in expected.items()
    ):
        raise ValueError("Invalid authored food inventory provenance")
    counts = {}
    for key in ("initial_checkpoint_cursor", "observed_boundaries", "complete_measurements",
                "unknown_measurements"):
        n = value.get(key)
        if type(n) is not int or not 0 <= n <= 2**53 - 1:
            raise ValueError("Invalid authored food coverage count")
        counts[key] = n
    endpoints = {}
    for key in ("initial_units", "final_units"):
        n = value.get(key, "missing")
        if n is not None and (type(n) is not int or not 0 <= n <= 2**53 - 1):
            raise ValueError("Food endpoint must be a complete count or explicit unknown")
        endpoints[key] = n
    known_endpoints = sum(n is not None for n in endpoints.values())
    if (
        counts["initial_checkpoint_cursor"] != parent_cursor
        or counts["observed_boundaries"] != decisions + 1
        or counts["complete_measurements"] + counts["unknown_measurements"]
        != counts["observed_boundaries"]
        or known_endpoints > counts["complete_measurements"]
        or 2 - known_endpoints > counts["unknown_measurements"]
    ):
        raise ValueError("Food coverage must reconcile with this window and its endpoints")
    return {**expected, **counts, **endpoints}

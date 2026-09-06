"""Declared workshop terrain semantics; legacy placement remains the default.

The broader shapes follow installed DFHack 0.47.05-r8 quickfort's generic
workshop tile predicate. This does not change materials, pathfinding, liquid,
occupancy, locality, furniture, farm plots, or construction rules.
"""

STRICT_FLOOR = "strict_floor/v1"
NATIVE_GROUND = "dfhack_047_ground/v1"
POLICIES = frozenset({STRICT_FLOOR, NATIVE_GROUND})
GROUND_SHAPES = ("FLOOR", "BOULDER", "PEBBLES", "TWIG", "SAPLING", "SHRUB")


def validate_policy(value: object) -> str:
    if not isinstance(value, str) or value not in POLICIES:
        raise ValueError("Unsupported workshop placement policy")
    return value


def policy_observation() -> dict:
    return {
        "policy": NATIVE_GROUND,
        "kinds": ["CarpenterWorkshop", "Still"],
        "allowed_ground_shapes": list(GROUND_SHAPES),
        "semantics": (
            "Every tile in the 3x3 footprint must be visible, unoccupied, dry, "
            "unfrozen ground of an allowed shape. Existing locality, citizen path, "
            "and available reachable material checks still apply. Placement queues "
            "native construction work, not a completed workshop. Other BUILD kinds "
            "retain their separate placement rules."
        ),
    }

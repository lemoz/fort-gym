"""Append-only extensions of a campaign's original cumulative limits."""

from __future__ import annotations

from copy import deepcopy
import re

BUDGET_KEYS = ("max_dispatches", "max_total_tokens")


def effective_budget(configuration: dict, extensions: list, usage: dict) -> dict:
    limits = {key: configuration[key] for key in BUDGET_KEYS}
    if not isinstance(extensions, list):
        raise ValueError("Budget extensions must be a list")
    previous_counts = dict(dispatched_requests=0, total_tokens=0)
    seen = set()
    for extension in extensions:
        if not isinstance(extension, dict) or set(extension) != {
            "schema_version",
            "checkpoint_sha256",
            "previous",
            "limits",
            "usage_at_extension",
        }:
            raise ValueError("Invalid budget extension fields")
        digest = extension["checkpoint_sha256"]
        if (
            extension["schema_version"] != "fortgym.campaign-budget-extension/v1"
            or not isinstance(digest, str)
            or re.fullmatch("[a-f0-9]{64}", digest) is None
            or digest in seen
            or extension["previous"] != limits
        ):
            raise ValueError("Budget extension lineage differs")
        next_limits = extension["limits"]
        if (
            not isinstance(next_limits, dict)
            or set(next_limits) != set(BUDGET_KEYS)
            or any(type(next_limits[k]) is not int or next_limits[k] < limits[k] for k in limits)
            or next_limits == limits
        ):
            raise ValueError("Budget limits must increase without reducing another limit")
        counts = extension["usage_at_extension"]
        if (
            not isinstance(counts, dict)
            or set(counts) != set(previous_counts)
            or any(
                type(counts[k]) is not int or not previous_counts[k] <= counts[k] <= usage[k]
                for k in previous_counts
            )
        ):
            raise ValueError("Budget extension usage does not preserve campaign history")
        previous_counts, limits = counts, next_limits
        seen.add(digest)
    return deepcopy(limits)

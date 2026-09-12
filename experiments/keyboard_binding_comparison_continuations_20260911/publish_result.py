"""Export an audited matched continuation to a new allowlisted public result file.

Commit the result before adding its immutable revision/digest to the comparison
index. This does not publish a website or certify a failed/incomplete native run.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from continuation_state import ROOT, read, require, sha
from storage_amendment import verify_binding

METRICS = (
    "population",
    "recorded_dead_citizens",
    "food_stock",
    "drink_stock",
    "completed_beds",
    "completed_workshops",
    "completed_farms",
    "functional_rooms",
    "wood_stock",
    "stone_stock",
)


def project(report: dict, window: dict, audit_sha256: str) -> dict:
    require(
        re.fullmatch(r"[a-f0-9]{64}", audit_sha256) is not None, "Invalid terminal audit digest"
    )
    identity = window["expected_campaign_id"]
    match = re.fullmatch(r"bindings-comparison-20260911-(sol|terra|astra)-r([12])", identity)
    require(
        match is not None,
        "Unknown matched campaign",
    )
    assert match is not None
    models = {"sol": "gpt-5.6-sol", "terra": "gpt-5.6-terra", "astra": "gpt-6-astra"}
    require(
        report["schema_version"] == "fortgym.private-matched-window-terminal-review/v1"
        and report["passed"] is True
        and report["campaign_id"] == identity
        and report["model"] == models[match[1]]
        and type(report["replicate"]) is int
        and report["replicate"] == int(match[2])
        and report["reasoning_effort"] == "medium"
        and report["source_revision"] == window["source_native_revision"]
        and report["image_id"] == window["source_image_id"]
        and report["source_checkpoint_sha256"] == window["continuation_checkpoint_sha256"]
        and report["first_step"] == 64,
        "Audited continuation identity differs",
    )
    status, count = report["status"], report["next_step"]
    require(
        type(count) is int
        and (
            (status == "completed" and count == 128 and report["stop_reason"] == "segment_limit")
            or (
                status == "paused"
                and 64 <= count < 128
                and report["stop_reason"] == "budget_limited_pause"
            )
        ),
        "Not a settled matched boundary",
    )
    require(
        report["responses"] == report["usage"]["accounted_responses"] == count
        and report["new_responses"] == count - 64
        and type(report["usage"]["total_tokens"]) is int
        and report["usage"]["total_tokens"]
        == window["returned_tokens_before_window"] + report["new_tokens"]
        and report["saved_elapsed_ticks"]
        == window["saved_elapsed_ticks_before_window"] + report["new_saved_elapsed_ticks"],
        "Audited continuation counters differ",
    )
    require(
        report["native_cleanup_verified"] is report["vm_teardown_verified"] is True
        and report["human_gameplay_rescue"] is False
        and report["source_checkpoint_fresh_load_verified"] is True
        and report["fresh_final_checkpoint_reload_verified"] is False,
        "Unverified teardown or human rescue",
    )
    result = {
        "schema_version": "fortgym.public-displayed-key-result/v1",
        "cohort_id": "bindings-comparison-20260911",
        "campaign_id": identity,
        "model": report["model"],
        "replicate": report["replicate"],
        "reasoning_effort": "medium",
        "source_revision": window["source_native_revision"],
        "image_id": window["source_image_id"],
        "seed_receipt_sha256": "eaf5fa5a40014719e6c313f33497740e536a8faa1c90a84c4e09dcc380ac0595",
        "condition_file_sha256": window["source_condition_sha256"],
        "trial_file_sha256": window["source_trial_sha256"],
        "response_limit": 128,
        "status": "saved" if status == "completed" else "budget_limited_pause",
        "responses": count,
        "returned_tokens": report["usage"]["total_tokens"],
        "reported_charge_usd": None,
        "human_gameplay_rescue": False,
        "native_teardown_verified": True,
        "vm_teardown_verified": True,
        "terminal_audit_sha256": audit_sha256,
        "checkpoint": {
            "next_step": count,
            "sha256": report["checkpoint_sha256"],
            "saved_elapsed_ticks": report["saved_elapsed_ticks"],
            "metrics": {key: report["saved_metrics"].get(key) for key in METRICS},
        },
        "evidence_details": {
            "source_result_sha256": window["source_result_sha256"],
            "source_checkpoint_sha256": window["continuation_checkpoint_sha256"],
            "source_checkpoint_fresh_load_verified": report[
                "source_checkpoint_fresh_load_verified"
            ],
            "fresh_final_checkpoint_reload_verified": report[
                "fresh_final_checkpoint_reload_verified"
            ],
            "new_responses": report["new_responses"],
            "new_tokens": report["new_tokens"],
            "new_saved_elapsed_ticks": report["new_saved_elapsed_ticks"],
            "confirmed_key_presses": report["confirmed_key_presses"],
            "clock_outcomes": report["clock_outcomes"],
        },
        "assessment": {
            "strong_model_ranking_supported": False,
            "gameplay_success_assessment": "not_inferred_by_export",
            "production_rates": None,
            "consumption_rates": None,
            "limits": [
                "A verified saved window is not a successful fortress or a model ranking.",
                "Stocks and sampled jobs do not establish production or consumption rates.",
                "Reported subscription and hardware charges remain unreported, not zero.",
                "The parent save was loaded; the new final save has not had a separate fresh reload.",
            ],
        },
    }
    if "storage_amendment" in report:
        result["evidence_details"]["storage_amendment"] = verify_binding(
            report["storage_amendment"], identity
        )
        result["assessment"]["limits"].append(
            "This window used a declared storage-only capacity amendment from 32 to 40 GiB; "
            "its VM storage configuration is not identical to preceding runs. "
            "Model, prompt, game controls, CPU and RAM are unchanged."
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--audit-sha256", required=True)
    parser.add_argument("--window", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(sha(args.audit) == args.audit_sha256, "Terminal audit changed")
    value = project(read(args.audit), read(args.window), args.audit_sha256)
    output = args.output.absolute()
    require(
        output.parent.resolve() == (ROOT / "experiments/evidence").resolve()
        and output.suffix == ".json"
        and not output.exists(),
        "Choose an unused public result path",
    )
    with output.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "written": str(output.relative_to(ROOT)),
                "sha256": sha(output),
                "website_published": False,
                "index_updated": False,
            }
        )
    )


if __name__ == "__main__":
    main()

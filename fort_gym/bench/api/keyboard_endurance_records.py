"""Audited own-save endurance chains; never discover active native artifacts."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from ..run.keyboard_config import validate_condition
from ..run.matched_endurance import next_window
from ..run.matched_result_chain import digest, validate_continuation
from .keyboard_cohort import PLAN_PATH, PLAN_SHA256, PROJECT_ROOT, _link, _read
from .keyboard_continuations import keyboard_continuations
from .keyboard_endurance_live import source_record

SCHEMA = "fortgym.public-keyboard-endurance-records/v1"
MAX_RECORD_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Publication:
    result_path: str
    result_sha256: str
    result_revision: str
    window_path: str
    window_sha256: str
    declaration_revision: str


# Add only independently audited, pushed result manifests in chronological order.
# No globbing, caller-provided paths, inferred runs or synthetic result records.
RESULTS: dict[str, tuple[Publication, ...]] = {
    "matched-20260910-astra-r1": (
        Publication(
            "experiments/evidence/keyboard_matched_astra_r1_continuation_64_128_20260911.json",
            "cb9cc0c5af8f158848493b1e7b3bb79f4f4736f185fbf7ce96fb157095e1d145",
            "0c2aaeb63f1a209cf7ec299a473a77911ddd10ed",
            "experiments/keyboard_matched_endurance_20260910/astra_r1-64-128.json",
            "37d2ed8db264f5941b8879543376110330294403274c2815922b6c3a057bc19f",
            "45bb05c903181b6b2e4f61df3a4c0a8eca05b818",
        ),
    ),
    "matched-20260910-sol-r1": (
        Publication(
            "experiments/evidence/keyboard_matched_sol_r1_continuation_64_128_20260911.json",
            "a155f9c940e242de32d216e9795291dc2093299b64ce57760b722ee7a0a33491",
            "91cab28293ed75f968fca12b4f1acbc5908da68e",
            "experiments/keyboard_matched_endurance_20260910/sol_r1-64-128.json",
            "f562e190020aa381508f0be375468303c314e3e9e1de2d36e8d937db4b2f0ef3",
            "45bb05c903181b6b2e4f61df3a4c0a8eca05b818",
        ),
    ),
}


def read_result(path: str, expected: str) -> dict:
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("A public record must remain inside the project")
    target = PROJECT_ROOT / relative
    if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_RECORD_BYTES:
        raise ValueError("Invalid public endurance record")
    data = target.read_bytes()
    if len(data) > MAX_RECORD_BYTES or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Endurance record differs from its registered digest")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("An endurance record must be an object")
    return value


def keyboard_endurance_records() -> dict:
    cohort = keyboard_continuations()
    plan = _read(PLAN_PATH, PLAN_SHA256)
    declared = {row["campaign_id"]: row for row in plan["execution_order"]}
    if RESULTS.keys() - declared.keys():
        raise ValueError("An endurance publication is outside the declared cohort")
    trials = []
    for baseline in cohort["trials"]:
        identity = baseline["campaign_id"]
        _, source, template, _ = source_record(identity)
        parent, parent_sha = baseline["result"], baseline["evidence_sha256"]
        chain = template["source_result_chain_sha256"].copy()
        condition = validate_condition(
            _read(
                "experiments/keyboard_matched_pilot_20260910/" + declared[identity]["condition"],
                parent["execution"]["condition_file_sha256"],
            )
        )
        windows = []
        for publication in RESULTS.get(identity, ()):
            for revision in (publication.result_revision, publication.declaration_revision):
                if re.fullmatch(r"[a-f0-9]{40}", revision) is None:
                    raise ValueError("Publication requires immutable source revisions")
            if publication.result_sha256 in chain:
                raise ValueError("An own-save result cannot repeat in its lineage")
            window = _read(publication.window_path, publication.window_sha256)
            expected = next_window(
                parent,
                parent_sha,
                chain,
                template,
                plan=plan,
                row=declared[identity],
                condition=condition,
            )
            if publication.window_sha256 != digest(expected) or window != expected:
                raise ValueError("Registered window differs from the original declared conditions")
            result = read_result(publication.result_path, publication.result_sha256)
            validate_continuation(result, parent, window, condition)
            if result["execution"]["declaration_revision"] != publication.declaration_revision:
                raise ValueError("Result does not bind its declared source revision")
            windows.append(
                {
                    "result": result,
                    "evidence_sha256": publication.result_sha256,
                    "evidence_url": _link(publication.result_path, publication.result_revision),
                    "declaration_url": _link(
                        publication.window_path, publication.declaration_revision
                    ),
                    "declaration_sha256": publication.window_sha256,
                }
            )
            parent, parent_sha, template = result, publication.result_sha256, window
            chain = [*chain, parent_sha]
        trials.append(
            {
                **{
                    key: baseline[key]
                    for key in ("campaign_id", "model", "replicate", "reasoning_effort")
                },
                "baseline_result_url": baseline["evidence_url"],
                "baseline_decision": source["cursor"],
                "windows": windows,
                "latest_result": parent,
                "latest_result_url": windows[-1]["evidence_url"]
                if windows
                else baseline["evidence_url"],
                "publication_state": "recorded_endurance"
                if windows
                else "decision_64_baseline_only",
            }
        )
    return {
        "schema_version": SCHEMA,
        "cohort_id": cohort["cohort_id"],
        "trials": trials,
        "declared_trials": len(trials),
        "recorded_endurance_windows": sum(len(row["windows"]) for row in trials),
        "recorded_endurance_boundaries": sum(
            entry["result"]["new_responses"] for row in trials for entry in row["windows"]
        ),
        "latest_saved_responses": sum(row["latest_result"]["next_decision"] for row in trials),
        "latest_saved_tokens": sum(
            row["latest_result"]["usage"]["campaign_returned_tokens"] for row in trials
        ),
        "comparison_decision_boundaries": plan["stages"]["comparison_decision_boundaries"],
        "year_two_elapsed_ticks": 403200,
        "strong_ranking_supported": False,
        "live_owner_status_included": False,
        "limits": [
            "Latest verified save per attempt. Unequal saved decision counts are not equal-budget model comparisons.",
            "A missing endurance result means no published audited window. The decision-64 baseline remains visible; it does not describe current live play.",
            "Each window retains its own save, model memory, original conditions and cumulative usage. Older window totals are not added twice.",
            "A year-two calendar crossing is not proof of a functioning or sustainable fortress. Food/drink stocks and current-job samples do not measure production rates.",
            "Reported subscription charges remain unknown, not zero. Same-seed pilot attempts do not establish a general model ranking.",
        ],
    }

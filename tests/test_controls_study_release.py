"""The completed controls comparison is reproducible from the release checkout."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.summarize_selected_workshop_cohort import summarize

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "experiments/evidence"
STUDY = EVIDENCE / "selected_workshop_runtime_v2_declaration_20260912.json"
SUMMARY = EVIDENCE / "selected_workshop_v2_cohort_20260912.json"
RESULTS = [
    EVIDENCE / f"selected_workshop_v2_p{pair}_{condition}_128_20260912.json"
    for pair in (1, 2, 3)
    for condition in ("keyboard", "shortcuts")
]


def read(path):
    return json.loads(path.read_bytes())


def test_imported_controls_evidence_and_conditions_keep_their_original_bytes():
    manifest = read(EVIDENCE / "controls_study_release_source_20260913.json")
    assert len(manifest["imported_files"]) == 10
    for row in manifest["imported_files"]:
        assert hashlib.sha256((ROOT / row["path"]).read_bytes()).hexdigest() == row["sha256"]
    study = read(STUDY)
    for name, digest in study["condition_file_sha256"].items():
        path = ROOT / study["source_condition_directory"] / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert manifest["native_runtime_changed"] is False
    assert manifest["website_changed"] is False


def test_all_six_actual_results_reproduce_the_published_summary_byte_for_byte():
    inputs = [STUDY, SUMMARY, *RESULTS]
    original = {path: path.read_bytes() for path in inputs}
    args = [sys.executable, "-m", "scripts.summarize_selected_workshop_cohort", "--study", str(STUDY)]
    for result in RESULTS:
        args.extend(["--result", str(result)])
    completed = subprocess.run(args, cwd=ROOT, check=True, capture_output=True)
    assert completed.stdout == SUMMARY.read_bytes()
    assert {path: path.read_bytes() for path in inputs} == original
    report = json.loads(completed.stdout)
    assert report == summarize(STUDY, list(reversed(RESULTS)))
    assert report["all_declared_terminal_manifests_supplied"] is True
    assert report["missing_results"] == []
    assert report["supplied_attempts"] == report["declared_attempts"] == 6
    assert report["returned_tokens_in_supplied_results"] == 22995467
    assert report["reported_charge_usd_for_supplied_results"] is None
    assert report["ranking_performed"] is False
    assert report["native_audit_performed"] is False


@pytest.mark.parametrize("result_path", RESULTS, ids=lambda path: path.stem)
def test_each_reported_control_condition_binds_to_its_retained_native_replay(result_path):
    result = read(result_path)
    identity = f'controls-v2-p{result["pair"]}-{result["condition"]}-1-128'
    directory = ROOT / "web/static/recordings"
    catalog = read(directory / "catalog.json")["recordings"]
    entry = next(row for row in catalog if row["id"] == identity)
    raw = (directory / f"{identity}.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
    recording = json.loads(raw)
    assert entry["audit_sha256"] == recording["audit_sha256"] == result["audit_sha256"]
    assert entry["source_revision"] == result["source_revision"]
    assert entry["control_profile"] == result["control_profile"]
    frames = recording["frames"]
    assert [frame["decision"] for frame in frames] == list(range(1, 129))
    assert sum(frame["after"]["ticks_advanced"] for frame in frames) == result["saved_elapsed_ticks"]
    assert sum(frame["accepted"] for frame in frames) == result["action_counts"]["accepted_actions"]
    shortcuts = sum("shortcut" in frame["action"] for frame in frames)
    assert shortcuts == result["action_counts"]["workshop"]["decisions"]
    if result["condition"] == "keyboard":
        assert shortcuts == 0
    else:
        assert shortcuts > 0


def test_current_quickstart_links_the_reproducible_controls_study():
    text = (ROOT / "docs/YEAR_TWO_QUICKSTART.md").read_text()
    assert "CONTROLS_STUDY_RESULTS.md" in text
    guide = (ROOT / "docs/CONTROLS_STUDY_RESULTS.md").read_text()
    assert "scripts.summarize_selected_workshop_cohort" in guide
    for path in RESULTS:
        assert path.name in guide

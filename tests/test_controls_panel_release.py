"""Published paired results integrate without replacing campaign navigation."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "experiments/evidence"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def manifest():
    return json.loads((EVIDENCE / "controls_panel_release_source_20260913.json").read_bytes())


def test_imported_public_files_and_delivery_receipt_remain_exact():
    source = manifest()
    assert source["published_website_revision"] == "2cdfee3131d3792b5cde8c6fadaeef742940f12e"
    assert len(source["imported_files"]) == 4
    for row in source["imported_files"]:
        assert sha((ROOT / row["path"]).read_bytes()) == row["sha256"]
    receipt = json.loads((ROOT / source["publication_receipt"]).read_bytes())
    assert receipt["revision"] == source["published_website_revision"]
    assert receipt["passed"] is True
    assert receipt["assets"]["/results"] == source["published_results_sha256"]
    assert len(receipt["replay_hashes"]) == 6
    assert receipt["catalog_recordings"] == 39
    assert receipt["catalog_frames"] == 3048


def test_panel_is_exact_and_all_other_results_content_is_preserved():
    source = manifest()
    html = (ROOT / "web/results.html").read_text()
    start = '  <section class="fl-section controls-study" id="controls-comparison"'
    end = '  <section class="fl-section" aria-labelledby="current-recordings-title">'
    assert html.count(start) == html.count(end) == 1
    panel = html[html.index(start):html.index(end)]
    assert sha(panel.encode()) == source["published_panel_sha256"]
    assert sha(html.encode()) == source["combined_results_sha256"]
    css = "  .controls-study tbody + tbody tr:first-child > * { border-top: 2px solid var(--cyan); }\n"
    assert html.count(css) == 1
    prior = html.replace(panel, "", 1).replace(css, "", 1)
    assert sha(prior.encode()) == source["previous_results_sha256"]
    desktop = '<a href="/campaigns">Campaigns</a>'
    mobile = '  <a href="/campaigns">Campaigns <span>08</span></a>\n'
    assert html.count(desktop) == html.count(mobile) == 1
    public = html.replace(desktop, "", 1).replace(mobile, "", 1)
    assert sha(public.encode()) == source["published_results_sha256"]


def test_download_and_reproducible_study_are_the_same_original_bytes():
    original = (EVIDENCE / "selected_workshop_v2_cohort_20260912.json").read_bytes()
    public = (ROOT / "web/static/controls-study-comparison.json").read_bytes()
    assert public == original
    assert sha(public) == "84db13cefc663f84c4016d2182ca9a34c974710517dab9640a15ab8919b9ef17"
    guide = (ROOT / "docs/CONTROLS_STUDY_RESULTS.md").read_text()
    assert "https://fortgym.live/results#controls-comparison" in guide
    assert "not yet a public Results panel" not in guide
    assert "controls_study_website_20260913.json" in guide
    assert "/results#controls-comparison" in (ROOT / "docs/YEAR_TWO_QUICKSTART.md").read_text()


def test_static_integration_does_not_claim_a_new_native_or_public_run():
    source = manifest()
    for field in ("model_calls", "gameplay_actions", "vm_starts"):
        assert source[field] == 0
    for field in (
        "existing_native_and_condition_files_changed",
        "original_results_recordings_and_outcomes_changed",
        "website_deployed_by_this_integration", "main_merged", "full_goal_complete",
    ):
        assert source[field] is False

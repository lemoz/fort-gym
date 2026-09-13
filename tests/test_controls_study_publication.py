"""Public paired-controls rows remain bound to the actual recorded study."""

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "web/static/controls-study-comparison.json"
SOURCE = "https://github.com/lemoz/fort-gym/blob/26edd37c0f5946bfb4f0a98d30ae432d8d590e7f"
SUMMARY_SHA = "84db13cefc663f84c4016d2182ca9a34c974710517dab9640a15ab8919b9ef17"


class ControlsPanel(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.inside = False
        self.rows = []
        self.row = None
        self.cell = None
        self.links = []
        self.text = []
        self.scrollers = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "section" and attrs.get("id") == "controls-comparison":
            self.inside = True
        if not self.inside:
            return
        if tag == "div" and attrs.get("role") == "region":
            self.scrollers.append(attrs)
        if tag == "tr" and "data-controls-pair" in attrs:
            self.row = {"attrs": attrs, "cells": [], "links": []}
        if self.row is not None and tag in ("td", "th"):
            self.cell = []
        if tag == "a":
            self.links.append(attrs)
            if self.row is not None:
                self.row["links"].append(attrs)

    def handle_data(self, data):
        if self.inside:
            self.text.append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row["cells"].append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        if tag == "section":
            self.inside = False


def report():
    return json.loads(REPORT.read_bytes())


def fmt(value: int) -> str:
    return f"{value:,}"


def test_public_summary_is_the_original_complete_single_seed_report():
    assert hashlib.sha256(REPORT.read_bytes()).hexdigest() == SUMMARY_SHA
    data = report()
    assert data["schema_version"] == "fortgym.selected-workshop-cohort-summary/v1"
    assert data["model"] == "gpt-6-astra"
    assert data["reasoning_effort"] == "medium"
    assert data["supplied_attempts"] == data["declared_attempts"] == 6
    assert data["common_response_boundary"] == 128
    assert data["missing_results"] == []
    assert data["ranking_performed"] is data["sustainability_assessed"] is False
    assert data["returned_tokens_in_supplied_results"] == 22995467
    assert data["reported_charge_usd_for_supplied_results"] is None


@pytest.mark.parametrize("pair", [1, 2, 3])
@pytest.mark.parametrize("condition", ["keyboard", "shortcuts"])
def test_visible_pair_values_and_links_match_the_original_replay(pair, condition):
    data = report()
    result = data["pairs"][pair - 1]["results"][condition]
    metrics = result["metrics"]
    panel = ControlsPanel((ROOT / "web/results.html").read_text())
    assert len(panel.rows) == 6
    row = next(row for row in panel.rows if row["attrs"]["data-controls-pair"] == str(pair)
               and row["attrs"]["data-controls-condition"] == condition)
    label = "Keyboard" if condition == "keyboard" else "Keyboard + shortcuts"
    assert row["cells"] == [
        f"Pair {pair} {label}", fmt(result["saved_elapsed_ticks"]),
        f'{metrics["population"]} / {metrics["recorded_dead_citizens"]}',
        " / ".join(str(metrics[key]) for key in
                   ("completed_beds", "completed_workshops", "completed_farms")),
        f'{metrics["food_stock"]} / {metrics["drink_stock"]}',
        fmt(result["returned_tokens"]), "Replay Result",
    ]
    identity = f"controls-v2-p{pair}-{condition}-1-128"
    assert [link["href"] for link in row["links"]] == [
        f"/?recording={identity}#watch-root",
        f'{SOURCE}/experiments/evidence/{result["result_file"]}',
    ]
    assert all(link.get("aria-label") for link in row["links"])
    directory = ROOT / "web/static/recordings"
    catalog = json.loads((directory / "catalog.json").read_bytes())["recordings"]
    entry = next(entry for entry in catalog if entry["id"] == identity)
    raw = (directory / f"{identity}.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
    recording = json.loads(raw)
    assert recording["audit_sha256"] == entry["audit_sha256"] == result["audit_sha256"]
    assert entry["source_revision"] == data["source_revision"]
    assert entry["control_profile"] == recording["control_profile"]
    expected = ("native_keyboard_bindings/v1" if condition == "keyboard"
                else "native_keyboard_selected_workshop_jobs/v1")
    assert entry["control_profile"] == expected
    frames = recording["frames"]
    assert [frame["decision"] for frame in frames] == list(range(1, 129))
    advanced = sum(frame["after"]["ticks_advanced"] for frame in frames)
    assert advanced == result["saved_elapsed_ticks"]
    assert result["final_checkpoint_fresh_reload_verified"] is False


def test_comparison_is_served_without_javascript_and_keeps_its_limits_visible():
    from fort_gym.bench.api.server import app

    client = TestClient(app)
    response = client.get("/results")
    assert response.status_code == 200
    assert response.content == (ROOT / "web/results.html").read_bytes()
    panel = ControlsPanel(response.text)
    assert len(panel.rows) == 6
    assert len(panel.scrollers) == 1
    assert panel.scrollers[0]["tabindex"] == "0"
    assert "scroll horizontally" in panel.scrollers[0]["aria-label"]
    text = " ".join(panel.text)
    for phrase in (
        "Astra Medium", "128-decision budget", "same 120 × 40 screen",
        "empty starting memory", "its instructions", "not ranked",
        "not independent seeds", "not mean equal game time", "22,995,467",
        "dollar charges are unreported, not $0", "not a completed product",
        "not production rates", "Year-Two endurance run",
        "do not claim another independent reload",
    ):
        assert phrase in text
    hrefs = {link["href"] for link in panel.links}
    assert "/static/controls-study-comparison.json" in hrefs
    assert f"{SOURCE}/docs/CONTROLS_STUDY_RESULTS.md" in hrefs
    declaration = "selected_workshop_runtime_v2_declaration_20260912.json"
    assert f"{SOURCE}/experiments/evidence/{declaration}" in hrefs
    payload = client.get("/static/controls-study-comparison.json")
    assert payload.status_code == 200 and payload.content == REPORT.read_bytes()
    assert response.text.index('id="matched-comparison"') < response.text.index(
        'id="controls-comparison"') < response.text.index('id="current-recordings-title"')


def test_existing_model_comparison_and_historical_field_remain_separate():
    html = (ROOT / "web/results.html").read_text()
    for marker in (
        'id="matched-boundary"', '/static/displayed-key-comparison.mjs',
        "data-published-recordings", "fort-eval-easy-p1-g7-v3", 'id="cohort-groups"',
    ):
        assert marker in html
    assert len(json.loads((ROOT / "web/static/recordings/catalog.json").read_text())[
        "recordings"]) == 39

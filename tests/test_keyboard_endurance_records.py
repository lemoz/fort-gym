"""Actual decision-64 baselines with explicit synthetic future-window fixtures."""

import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api import keyboard_endurance_records as records
from fort_gym.bench.api.keyboard_continuations import keyboard_continuations
from fort_gym.bench.run.matched_result_chain import digest, encoded
from tests.test_campaign_matched_endurance_window import synthetic_child


def test_actual_six_saved_baselines_do_not_invent_endurance_results(monkeypatch):
    monkeypatch.setattr(records, "RESULTS", {})
    baseline = keyboard_continuations()
    result = records.keyboard_endurance_records()
    assert result["recorded_endurance_windows"] == result["recorded_endurance_boundaries"] == 0
    assert result["latest_saved_responses"] == 384 and result["latest_saved_tokens"] == 11403734
    assert result["declared_trials"] == 6
    assert result["strong_ranking_supported"] is result["live_owner_status_included"] is False
    for row, before in zip(result["trials"], baseline["trials"], strict=True):
        assert row["publication_state"] == "decision_64_baseline_only"
        assert row["latest_result"] == before["result"] and row["windows"] == []
        assert row["latest_result_url"] == before["evidence_url"]
    assert keyboard_continuations() == baseline


def test_actual_astra_endurance_result_preserves_audited_outcome_and_unequal_budgets():
    result = records.keyboard_endurance_records()
    assert result["recorded_endurance_windows"] == 1
    assert result["recorded_endurance_boundaries"] == 64
    assert result["latest_saved_responses"] == 448
    assert result["latest_saved_tokens"] == 13479220
    astra, *others = result["trials"]
    assert astra["campaign_id"] == "matched-20260910-astra-r1"
    assert astra["publication_state"] == "recorded_endurance"
    assert all(
        row["latest_result"]["next_decision"] == 64 and row["windows"] == [] for row in others
    )
    saved = astra["latest_result"]
    assert saved["next_decision"] == 128 and saved["new_responses"] == 64
    assert saved["saved_elapsed_ticks"] == 51400
    assert (
        saved["audit_sha256"] == "68afc4f0729cc37b28c41d6d7399239bace42aff5a59d9270e4c74c08c169f86"
    )
    assert (
        saved["checkpoint_sha256"]
        == "bff0afda99c39e25fe9db7aeb01db77ab6a819cb20c5d82670a2188952cceec2"
    )
    metrics = saved["saved_metrics"]
    assert (metrics["population"], metrics["recorded_dead_citizens"]) == (7, 0)
    assert (
        metrics["completed_beds"],
        metrics["completed_farms"],
        metrics["completed_workshops"],
    ) == (5, 2, 3)
    assert (metrics["food_stock"], metrics["drink_stock"]) == (29, 121)
    assert saved["year_two_reached"] is saved["sustainability_established"] is False
    assert saved["native_cleanup_verified"] is saved["vm_teardown_verified"] is True
    assert saved["source_checkpoint_fresh_load_verified"] is True
    assert saved["final_fresh_reload_verified"] is False
    assert saved["usage"]["reported_charge_usd"] is None
    assert (
        astra["windows"][0]["evidence_sha256"]
        == "cb9cc0c5af8f158848493b1e7b3bb79f4f4736f185fbf7ce96fb157095e1d145"
    )
    assert "/0c2aaeb63f1a209cf7ec299a473a77911ddd10ed/" in astra["latest_result_url"]
    assert result["strong_ranking_supported"] is result["live_owner_status_included"] is False


@pytest.fixture
def published(tmp_path, monkeypatch):
    original = records._read
    monkeypatch.setattr(records, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(records, "RESULTS", {})
    monkeypatch.setattr(
        records,
        "_read",
        lambda path, expected: (
            records.read_result(path, expected)
            if path.startswith("fixture-")
            else original(path, expected)
        ),
    )
    identity = "matched-20260910-astra-r1"
    row, source, template, _ = records.source_record(identity)
    parent = row["result"]
    parent_sha = source["public_result_sha256"]
    chain = template["source_result_chain_sha256"].copy()
    plan = original(records.PLAN_PATH, records.PLAN_SHA256)
    declared = next(row for row in plan["execution_order"] if row["campaign_id"] == identity)
    condition = original(
        "experiments/keyboard_matched_pilot_20260910/astra-condition.json",
        parent["execution"]["condition_file_sha256"],
    )

    def append(responses=None, change=None):
        nonlocal parent, parent_sha, template, chain
        window = records.next_window(
            parent, parent_sha, chain, template, plan=plan, row=declared, condition=condition
        )
        child = synthetic_child(parent, window, responses)
        child["execution"]["declaration_revision"] = "b" * 40
        if change:
            change(child)
        index = len(records.RESULTS.get(identity, ()))
        result_path, window_path = f"fixture-result-{index}.json", f"fixture-window-{index}.json"
        (tmp_path / result_path).write_bytes(encoded(child))
        (tmp_path / window_path).write_bytes(encoded(window))
        publication = records.Publication(
            result_path, digest(child), "a" * 40, window_path, digest(window), "b" * 40
        )
        records.RESULTS[identity] = (*records.RESULTS.get(identity, ()), publication)
        parent, parent_sha, template = child, digest(child), window
        chain = [*chain, parent_sha]
        return child, publication

    return append


@pytest.mark.parametrize("target", [128, 256, 512, 1024, 1280])
def test_longer_chains_keep_latest_totals_without_counting_parents_twice(published, target):
    cursor = 64
    while cursor < target:
        child, _ = published()
        cursor = child["next_decision"]
    result = records.keyboard_endurance_records()
    own = result["trials"][0]
    assert own["latest_result"] == child
    assert own["publication_state"] == "recorded_endurance"
    assert result["recorded_endurance_boundaries"] == target - 64
    assert result["latest_saved_responses"] == 384 + target - 64
    assert result["latest_saved_tokens"] == 11403734 + (target - 64) * 100
    assert all(not row["windows"] for row in result["trials"][1:])
    assert [r["result"]["next_decision"] for r in own["windows"]][-1] == target


@pytest.mark.parametrize("responses", [0, 1, 31, 63])
def test_saved_budget_pause_remains_a_pause_and_can_resume(published, responses):
    child, _ = published(responses=responses)
    result = records.keyboard_endurance_records()
    own = result["trials"][0]
    assert own["latest_result"]["status"] == "paused"
    assert own["latest_result"]["next_decision"] == 64 + responses
    assert result["latest_saved_responses"] == 384 + responses
    later, _ = published()
    assert later["next_decision"] == 128
    assert records.keyboard_endurance_records()["trials"][0]["latest_result"] == later


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "gpt-5.6-sol"),
        ("prior_checkpoint_sha256", "f" * 64),
        ("source_result_sha256", "e" * 64),
        ("new_responses", True),
        ("saved_elapsed_ticks", -1),
        ("vm_teardown_verified", False),
        ("human_gameplay_rescue", True),
        ("memory_preserved_at_start", False),
    ],
)
def test_invalid_own_save_lineage_never_becomes_a_result(published, field, value):
    published(change=lambda child: child.update({field: value}))
    with pytest.raises(ValueError):
        records.keyboard_endurance_records()


def test_reordered_or_repeated_windows_and_wrong_source_revision_are_rejected(published):
    published()
    published()
    identity = "matched-20260910-astra-r1"
    original = records.RESULTS[identity]
    for changed in (original[::-1], (original[0], original[0])):
        records.RESULTS[identity] = changed
        with pytest.raises(ValueError):
            records.keyboard_endurance_records()
    first = original[0]
    records.RESULTS[identity] = (
        records.Publication(
            first.result_path,
            first.result_sha256,
            "main",
            first.window_path,
            first.window_sha256,
            first.declaration_revision,
        ),
    )
    with pytest.raises(ValueError):
        records.keyboard_endurance_records()


def test_route_matches_records_and_does_not_change_the_live_or_historical_routes(published):
    from fort_gym.bench.api import server

    client = TestClient(server.app)
    before = client.get("/public/keyboard-cohort-continuations").json()
    published()
    response = client.get("/public/keyboard-cohort-endurance-records")
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    assert response.json() == records.keyboard_endurance_records()
    assert client.get("/public/keyboard-cohort-continuations").json() == before
    assert (
        client.get("/public/keyboard-cohort-endurance-active").json()["status"] == "not_connected"
    )
    assert client.get("/protocols/unknown").status_code == 404
    identity = "matched-20260910-astra-r1"
    first = records.RESULTS[identity][0]
    records.RESULTS[identity] = (
        records.Publication(
            first.result_path,
            "0" * 64,
            first.result_revision,
            first.window_path,
            first.window_sha256,
            first.declaration_revision,
        ),
    )
    response = client.get("/public/keyboard-cohort-endurance-records")
    assert response.status_code == 503 and "/Users/" not in response.text


def test_record_reader_rejects_escape_symlink_and_oversize(tmp_path, monkeypatch):
    monkeypatch.setattr(records, "PROJECT_ROOT", tmp_path)
    path = tmp_path / "small.json"
    path.write_bytes(b"{}\n")
    import hashlib

    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert records.read_result("small.json", expected) == {}
    for name in (str(path), "../small.json"):
        with pytest.raises(ValueError):
            records.read_result(name, expected)
    (tmp_path / "link.json").symlink_to(path)
    with pytest.raises(ValueError):
        records.read_result("link.json", expected)
    monkeypatch.setattr(records, "MAX_RECORD_BYTES", 1)
    with pytest.raises(ValueError):
        records.read_result("small.json", expected)


@pytest.mark.parametrize("target", [128, 1280])
def test_website_renders_latest_saves_and_loads_window_details_only_when_opened(published, target):
    from fort_gym.bench.api.keyboard_cohort import PROJECT_ROOT

    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    cursor = 64
    while cursor < target:
        child, _ = published()
        cursor = child["next_decision"]
    data = records.keyboard_endurance_records()
    program = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.open = false; }
  set textContent(v) { this.text = String(v); this.children = []; }
  get textContent() { return (this.text || '') + this.children.map(n => n.textContent).join(' '); }
  setAttribute(k,v) { this[k] = v; } appendChild(v) { this.children.push(v); }
  replaceChildren(...v) { this.children = v; this.text = ''; } addEventListener(k,v) { this.events[k] = v; }
}
const data = JSON.parse(fs.readFileSync(0, 'utf8')), nodes = {}; let fail = false;
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  document: {getElementById: id => nodes[id] ||= new Element('div'), createElement: tag => new Element(tag)},
  fetch: async url => { assert.equal(url, '/public/keyboard-cohort-endurance-records'); return {ok: !fail, json: async () => data}; },
  AbortController, setTimeout, clearTimeout
});
(async () => {
  await new Promise(setImmediate);
  const content = nodes['endurance-records-content'];
  assert.equal(content.hidden, false);
  assert.match(content.textContent, /Decision-64 baseline; no published endurance result/);
  assert.match(content.textContent, /Saved endurance window/);
  assert.match(content.textContent, /Different response totals are not equal-budget comparisons/);
  const all = () => { const rows=[]; const visit=n=>{rows.push(n);n.children.forEach(visit);};visit(content);return rows; };
  assert.equal(all().filter(n=>n.tag==='table').length,1);
  const bodies=all().filter(n=>n.tag==='tbody'); assert.equal(bodies[0].children.length,6);
  const detail=all().find(n=>n.tag==='details'); assert.ok(detail);
  detail.open=true; detail.events.toggle();
  assert.equal(all().filter(n=>n.tag==='table').length,2);
  assert.equal(all().filter(n=>n.tag==='tbody')[1].children.length,64);
  detail.events.toggle(); assert.equal(all().filter(n=>n.tag==='table').length,2);
  assert.match(content.textContent, /unreported, not \$0/);
  assert.match(content.textContent, /not yet verified/);
  const links=all().filter(n=>n.tag==='a');
  assert.equal(links[0].href,data.trials[0].windows[0].evidence_url);
  assert.equal(links.at(-1).href,data.trials[0].windows[0].declaration_url);
  const saved=content.textContent; fail=true; await nodes['refresh-endurance-records'].events.click();
  assert.equal(content.textContent,saved); assert.match(nodes['endurance-records-status'].textContent,/Refresh failed/);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run(
        [
            node,
            "-e",
            program,
            str(PROJECT_ROOT / "web/static/campaign-endurance-records.js"),
        ],
        # Histories can exceed Linux's per-argument limit; keep payloads off argv.
        input=json.dumps(data),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr

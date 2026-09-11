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
    assert (
        result["recorded_endurance_windows"]
        == result["recorded_endurance_boundaries"]
        == 0
    )
    assert (
        result["latest_saved_responses"] == 384
        and result["latest_saved_tokens"] == 11403734
    )
    assert result["declared_trials"] == 6
    assert (
        result["strong_ranking_supported"]
        is result["live_owner_status_included"]
        is False
    )
    for row, before in zip(result["trials"], baseline["trials"], strict=True):
        assert row["publication_state"] == "decision_64_baseline_only"
        assert row["latest_result"] == before["result"] and row["windows"] == []
        assert row["latest_result_url"] == before["evidence_url"]
    assert keyboard_continuations() == baseline


def test_actual_astra_endurance_result_preserves_audited_outcome_and_unequal_budgets(
    monkeypatch,
):
    identity = "matched-20260910-astra-r1"
    monkeypatch.setattr(records, "RESULTS", {identity: records.RESULTS[identity]})
    result = records.keyboard_endurance_records()
    assert result["recorded_endurance_windows"] == 1
    assert result["recorded_endurance_boundaries"] == 64
    assert result["latest_saved_responses"] == 448
    assert result["latest_saved_tokens"] == 13479220
    astra, *others = result["trials"]
    assert astra["campaign_id"] == "matched-20260910-astra-r1"
    assert astra["publication_state"] == "recorded_endurance"
    assert all(
        row["latest_result"]["next_decision"] == 64 and row["windows"] == []
        for row in others
    )
    saved = astra["latest_result"]
    assert saved["next_decision"] == 128 and saved["new_responses"] == 64
    assert saved["saved_elapsed_ticks"] == 51400
    assert (
        saved["audit_sha256"]
        == "68afc4f0729cc37b28c41d6d7399239bace42aff5a59d9270e4c74c08c169f86"
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
    assert (
        result["strong_ranking_supported"]
        is result["live_owner_status_included"]
        is False
    )


def test_astra_and_sol_128_records_remain_independent_before_cohort_complete(
    monkeypatch,
):
    monkeypatch.setattr(
        records,
        "RESULTS",
        {
            identity: records.RESULTS[identity]
            for identity in ("matched-20260910-astra-r1", "matched-20260910-sol-r1")
        },
    )
    result = records.keyboard_endurance_records()
    assert result["recorded_endurance_windows"] == 2
    assert result["recorded_endurance_boundaries"] == 128
    assert result["latest_saved_responses"] == 512
    assert result["latest_saved_tokens"] == 15508434
    astra, sol, *others = result["trials"]
    assert all(row["latest_result"]["next_decision"] == 128 for row in (astra, sol))
    assert all(
        row["latest_result"]["next_decision"] == 64 and row["windows"] == []
        for row in others
    )
    assert (
        astra["windows"][0]["evidence_sha256"]
        == "cb9cc0c5af8f158848493b1e7b3bb79f4f4736f185fbf7ce96fb157095e1d145"
    )
    assert sol["campaign_id"] == "matched-20260910-sol-r1"
    assert (
        sol["windows"][0]["evidence_sha256"]
        == "a155f9c940e242de32d216e9795291dc2093299b64ce57760b722ee7a0a33491"
    )
    saved = sol["latest_result"]
    assert saved["saved_elapsed_ticks"] == 20000 and saved["new_saved_ticks"] == 14500
    assert (
        saved["audit_sha256"]
        == "60134d9949f6815af0728bb9aee775f98661149295293f20993e5acd3c6cf0d9"
    )
    assert (
        saved["checkpoint_sha256"]
        == "5c8e263dcdbf12908eb33d7317eaa1f88545d3a6d0c4fbd151fe69224e391b3f"
    )
    assert (
        saved["prior_checkpoint_sha256"]
        != astra["latest_result"]["prior_checkpoint_sha256"]
    )
    metrics = saved["saved_metrics"]
    assert (metrics["population"], metrics["recorded_dead_citizens"]) == (7, 0)
    assert (
        metrics["completed_beds"],
        metrics["completed_farms"],
        metrics["completed_workshops"],
    ) == (0, 0, 0)
    assert (metrics["food_stock"], metrics["drink_stock"]) == (50, 60)
    assert saved["new_window_activity"]["boundaries_with_job_type"]["Dig"] == 56
    assert saved["usage"]["campaign_returned_tokens"] == 3522467
    assert saved["year_two_reached"] is saved["sustainability_established"] is False
    assert saved["final_fresh_reload_verified"] is False
    assert saved["native_cleanup_verified"] is saved["vm_teardown_verified"] is True
    assert saved["usage"]["reported_charge_usd"] is None
    assert "/91cab28293ed75f968fca12b4f1acbc5908da68e/" in sol["latest_result_url"]
    assert (
        result["strong_ranking_supported"]
        is result["live_owner_status_included"]
        is False
    )


def test_five_audited_128_records_keep_astra_two_at_its_actual_baseline(monkeypatch):
    monkeypatch.setattr(
        records,
        "RESULTS",
        {
            identity: publications
            for identity, publications in records.RESULTS.items()
            if identity != "matched-20260910-astra-r2"
        },
    )
    result = records.keyboard_endurance_records()
    assert result["recorded_endurance_windows"] == 5
    assert result["recorded_endurance_boundaries"] == 320
    assert result["latest_saved_responses"] == 704
    assert result["latest_saved_tokens"] == 20294864
    trials = {row["campaign_id"]: row for row in result["trials"]}
    assert trials["matched-20260910-astra-r2"]["latest_result"]["next_decision"] == 64
    assert trials["matched-20260910-astra-r2"]["windows"] == []
    expected = {
        "matched-20260910-terra-r1": (
            13000,
            2871632,
            "b17449c294ab154126192ab926603dfd59589114",
        ),
        "matched-20260910-terra-r2": (
            32500,
            4109237,
            "1f3b10db4e35fb9560254cb1bd789838dedd3264",
        ),
        "matched-20260910-sol-r2": (
            13800,
            3270294,
            "840402a411d69e868a6b93429d35a8f6502ca52f",
        ),
    }
    for identity, (ticks, tokens, revision) in expected.items():
        row = trials[identity]
        saved = row["latest_result"]
        assert saved["next_decision"] == 128 and saved["saved_elapsed_ticks"] == ticks
        assert saved["usage"]["campaign_returned_tokens"] == tokens
        assert saved["usage"]["reported_charge_usd"] is None
        assert saved["human_gameplay_rescue"] is saved["year_two_reached"] is False
        assert saved["sustainability_established"] is False
        assert saved["saved_metrics"]["population"] == 7
        assert all(
            saved["saved_metrics"][key] == 0
            for key in ("completed_beds", "completed_farms", "completed_workshops")
        )
        assert "/" + revision + "/" in row["latest_result_url"]
    assert result["strong_ranking_supported"] is False


def test_all_six_audited_results_share_128_decisions_without_inventing_success():
    result = records.keyboard_endurance_records()
    assert result["recorded_endurance_windows"] == 6
    assert result["recorded_endurance_boundaries"] == 384
    assert result["latest_saved_responses"] == 768
    assert result["latest_saved_tokens"] == 22707069
    for row in result["trials"]:
        saved = row["latest_result"]
        assert saved["next_decision"] == 128 and len(row["windows"]) == 1
        assert saved["saved_metrics"]["population"] == 7
        assert saved["saved_metrics"]["recorded_dead_citizens"] == 0
        assert saved["source_checkpoint_fresh_load_verified"] is True
        assert saved["native_cleanup_verified"] is saved["vm_teardown_verified"] is True
        assert saved["human_gameplay_rescue"] is saved["year_two_reached"] is False
        assert saved["sustainability_established"] is False
        assert saved["final_fresh_reload_verified"] is False
        assert saved["usage"]["reported_charge_usd"] is None
    astra = result["trials"][-1]
    assert astra["campaign_id"] == "matched-20260910-astra-r2"
    saved = astra["latest_result"]
    assert saved["saved_elapsed_ticks"] == 39900
    assert saved["usage"]["campaign_returned_tokens"] == 4389202
    metrics = saved["saved_metrics"]
    assert tuple(
        metrics[key]
        for key in (
            "completed_beds",
            "completed_farms",
            "completed_workshops",
            "food_stock",
            "drink_stock",
        )
    ) == (6, 2, 3, 40, 128)
    assert metrics["functional_rooms"] is None
    assert "/b40b7417b7def266eb9e8c8e4a56c5c631b78490/" in astra["latest_result_url"]
    assert result["strong_ranking_supported"] is False


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
    declared = next(
        row for row in plan["execution_order"] if row["campaign_id"] == identity
    )
    condition = original(
        "experiments/keyboard_matched_pilot_20260910/astra-condition.json",
        parent["execution"]["condition_file_sha256"],
    )

    def append(responses=None, change=None):
        nonlocal parent, parent_sha, template, chain
        window = records.next_window(
            parent,
            parent_sha,
            chain,
            template,
            plan=plan,
            row=declared,
            condition=condition,
        )
        child = synthetic_child(parent, window, responses)
        child["execution"]["declaration_revision"] = "b" * 40
        if change:
            change(child)
        index = len(records.RESULTS.get(identity, ()))
        result_path, window_path = (
            f"fixture-result-{index}.json",
            f"fixture-window-{index}.json",
        )
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
def test_longer_chains_keep_latest_totals_without_counting_parents_twice(
    published, target
):
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


def test_reordered_or_repeated_windows_and_wrong_source_revision_are_rejected(
    published,
):
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


def test_route_matches_records_and_does_not_change_the_live_or_historical_routes(
    published,
):
    from fort_gym.bench.api import server

    client = TestClient(server.app)
    before = client.get("/public/keyboard-cohort-continuations").json()
    published()
    response = client.get("/public/keyboard-cohort-endurance-records")
    assert (
        response.status_code == 200 and "no-store" in response.headers["cache-control"]
    )
    assert response.json() == records.keyboard_endurance_records()
    assert client.get("/public/keyboard-cohort-continuations").json() == before
    assert (
        client.get("/public/keyboard-cohort-endurance-active").json()["status"]
        == "not_connected"
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
def test_website_renders_latest_saves_and_loads_window_details_only_when_opened(
    published, target
):
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

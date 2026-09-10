import copy
import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api import keyboard_cohort as cohort
from fort_gym.bench.api import keyboard_continuations as records


@pytest.fixture
def saved():
    row = cohort.keyboard_cohort()["trials"][0]
    path, digest, _ = records.RESULTS[row["campaign_id"]]
    return records._read(path, digest), row


def test_actual_saved_results_keep_all_declared_slots_and_original_records():
    before = cohort.keyboard_cohort()
    data = records.keyboard_continuations()
    assert cohort.keyboard_cohort() == before
    assert data["recorded_windows"] == len(records.RESULTS)
    assert data["declared_windows"] == 6
    assert data["strong_ranking_supported"] is data["live_owner_status_included"] is False
    assert [row["campaign_id"] for row in data["trials"]] == [
        row["campaign_id"] for row in before["trials"]
    ]
    assert [row["result"]["saved_elapsed_ticks"] for row in data["trials"][:3]] == [
        18200,
        5500,
        13000,
    ]
    assert [row["result"]["new_saved_ticks"] for row in data["trials"][:3]] == [7000, 3000, 6000]
    for row in data["trials"]:
        if row["campaign_id"] in records.RESULTS:
            assert row["publication_state"] == "recorded"
            assert row["result"]["source_checkpoint_fresh_load_verified"] is True
            assert row["result"]["final_fresh_reload_verified"] is False
            assert row["evidence_url"].startswith("https://github.com/lemoz/fort-gym/blob/")
        else:
            assert row["result"] is row["evidence_url"] is row["evidence_sha256"] is None
            assert row["publication_state"] == "no_published_result"


@pytest.mark.parametrize(
    "path,value",
    [
        (("campaign_id",), "matched-20260910-sol-r1"),
        (("prior_checkpoint_sha256",), "a" * 64),
        (("source_result_sha256",), "a" * 64),
        (("model",), "gpt-5.6-sol"),
        (("replicate",), True),
        (("screen_size",), [80, 25]),
        (("prompt_profile",), "other"),
        (("memory_preserved_at_start",), 1),
        (("prompt_change",), True),
        (("budget_extension",), True),
        (("human_gameplay_rescue",), True),
        (("new_native_save_losses",), False),
        (("execution", "data_disk_gib"), 24),
        (("execution", "window_sha256"), "f" * 64),
        (("execution", "binding_sha256"), cohort.ORIGINAL_BINDING),
        (("initial_metrics", "completed_workshops"), 0),
        (("new_responses",), True),
        (("new_responses",), 33),
        (("next_decision",), 63),
        (("new_saved_ticks",), 18200),
        (("saved_elapsed_ticks",), -1),
        (("saved_metrics", "completed_workshops"), True),
        (("final_fresh_reload_verified",), 0),
        (("checkpoint_sha256",), "bad"),
        (("year_two_reached",), True),
        (("status",), "failed"),
        (("stop_reason",), "budget_limited_pause"),
        (("usage", "reported_charge_usd"), 0),
        (("usage", "new_returned_tokens"), -1),
        (("usage", "returned_tokens_before_window"), 0),
        (("usage", "campaign_returned_tokens"), 1425155),
        (("usage", "campaign_accounted_responses"), 32),
        (("new_window_timeline",), []),
        (("new_window_clock_outcomes",), {"no_error": 31}),
        (("sustainability_established",), True),
    ],
)
def test_mismatched_origins_counts_and_claims_are_rejected(saved, path, value):
    result, row = saved
    target = result
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        records.validate_result(result, row)


@pytest.mark.parametrize(
    "field,value",
    [
        ("decision", 32),
        ("new_elapsed_ticks", -1),
        ("campaign_elapsed_ticks", 7000),
        ("accepted", 1),
        ("metrics", {}),
    ],
)
def test_each_decision_reconciles(saved, field, value):
    result, row = saved
    result["new_window_timeline"][0][field] = value
    with pytest.raises(ValueError):
        records.validate_result(result, row)


def test_unpublished_is_not_failure_and_bad_digest_is_unavailable(monkeypatch):
    from fort_gym.bench.api import server

    client = TestClient(server.app)
    before = client.get("/public/keyboard-cohort").json()
    route = "/public/keyboard-cohort-continuations"
    response = client.get(route)
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    assert response.json() == records.keyboard_continuations()
    assert client.get("/public/keyboard-cohort").json() == before
    page = client.get("/campaigns").text
    assert "Verified continuation saves" in page and "Initial 32-decision windows" in page
    assert "/static/campaign-continuation-records.js?v=1" in page
    assert client.get("/static/campaign-continuation-records.js").status_code == 200
    identity = "matched-20260910-astra-r1"
    original = records.RESULTS[identity]
    monkeypatch.delitem(records.RESULTS, identity)
    assert client.get(route).json()["trials"][0]["result"] is None
    monkeypatch.setitem(records.RESULTS, identity, (original[0], "0" * 64, original[2]))
    response = client.get(route)
    assert response.status_code == 503 and "/Users/" not in response.text


def test_budget_pause_can_remain_a_saved_result_without_claiming_window_completion(saved):
    result, row = saved
    result = copy.deepcopy(result)
    result.update(
        status="paused", stop_reason="budget_limited_pause", new_responses=31, next_decision=63
    )
    result["new_window_timeline"] = result["new_window_timeline"][:-1]
    last = result["new_window_timeline"][-1]
    result["saved_elapsed_ticks"] = last["campaign_elapsed_ticks"]
    result["new_saved_ticks"] = last["new_elapsed_ticks"]
    result["saved_metrics"] = last["metrics"]
    result["usage"]["campaign_accounted_responses"] = 63
    result["new_window_clock_outcomes"] = {"no_error": 31}
    records.validate_result(result, row)


def test_recorded_table_shows_new_and_cumulative_history_and_survives_refresh_failure():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    program = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; }
  set textContent(v) { this.text = String(v); this.children = []; }
  get textContent() { return (this.text || '') + this.children.map(n => n.textContent).join(' '); }
  setAttribute(k,v) { this[k] = v; } appendChild(v) { this.children.push(v); }
  replaceChildren(...v) { this.children = v; this.text = ''; } addEventListener(k,v) { this.events[k] = v; }
}
const data = JSON.parse(process.argv[2]), nodes = {}; let fail = false;
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  document: {getElementById: id => nodes[id] ||= new Element('div'), createElement: tag => new Element(tag)},
  fetch: async url => { assert.equal(url, '/public/keyboard-cohort-continuations'); return {ok: !fail, json: async () => data}; },
  AbortController, setTimeout, clearTimeout
});
(async () => {
  await new Promise(setImmediate);
  const content = nodes['continuation-records-content'];
  assert.equal(content.hidden, false);
  assert.match(content.textContent, /7,000 \/ 18,200/);
  assert.match(content.textContent, /3,000 \/ 5,500/);
  assert.match(content.textContent, /6,000 \/ 13,000/);
  assert.match(content.textContent, /unsupported_native_keys: 1/);
  assert.match(content.textContent, /1,425,155 \/ 2,468,751/);
  assert.match(content.textContent, /700,489 \/ 1,493,253/);
  assert.match(content.textContent, /unreported, not \$0/);
  assert.match(content.textContent, /not yet verified/);
  assert.match(content.textContent, /Window complete; campaign unfinished/);
  assert.match(content.textContent, /No published continuation/);
  const all=[]; const walk=n=>{all.push(n);n.children.forEach(walk);}; walk(content);
  const bodies=all.filter(n=>n.tag==='tbody'); assert.equal(bodies[0].children.length,6);
  assert.equal(bodies.length-1,data.recorded_windows);
  assert.equal(bodies.slice(1).reduce((n,b)=>n+b.children.length,0),data.recorded_windows*32);
  assert.equal(all.find(n=>n.tag==='a').href,data.trials[0].evidence_url);
  const saved=content.textContent; fail=true; await nodes['refresh-continuation-records'].events.click();
  assert.equal(content.textContent,saved); assert.match(nodes['continuation-records-status'].textContent,/Refresh failed/);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run(
        [
            node,
            "-e",
            program,
            str(cohort.PROJECT_ROOT / "web/static/campaign-continuation-records.js"),
            json.dumps(records.keyboard_continuations()),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr

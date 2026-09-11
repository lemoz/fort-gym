"""Actual immutable parents with synthetic live observations, never new game results."""

from copy import deepcopy
import json
import shutil
import subprocess
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api import keyboard_endurance_live_v2 as live
from fort_gym.bench.api.keyboard_cohort import PROJECT_ROOT


@pytest.fixture
def value():
    return {
        **live.identity_fields("matched-20260910-astra-r1"),
        "controller_alive": True,
        "observed_at_unix": int(time.time()),
        "responses": 65,
        "returned_tokens": 6500,
        "unsettled_claims": 1,
        "observed_elapsed_ticks_lower_bound": 500,
        "teardown_reported": None,
        "reported_charge_usd": None,
    }


WINDOWS = {
    "astra-r1": "9fa3b4160f5df536a9f65cb33b00d9dcb4e28660acab8b789729434a6621a61a",
    "sol-r1": "07431d4bbbb35c0f639ee9346610397a72696db4af6609711aada2bc511793f2",
    "terra-r1": "30302a01d3476864ae95e532efbad30d008b6715acf76a893b6260a7d00b2ddc",
    "terra-r2": "a7831a06f07d464f2d4f34a0b250ce7b8d7f8acb6fe416f34dc7a164a9a296a4",
    "sol-r2": "f1a8e269e762529a7f404e19f83dec23476f4a00b4b77e796c44e1937d813aa4",
    "astra-r2": "7cc1c4311eddd8e25f90e760ffd43e502d93eb2b06f3070160aca4249996c81d",
}


@pytest.mark.parametrize("identity,expected_sha", WINDOWS.items())
def test_all_six_windows_match_the_pushed_declarations_and_own_128_parent(
    value, identity, expected_sha
):
    identity = "matched-20260910-" + identity
    row, parent, window = live.source_record(identity)
    value.update(live.identity_fields(identity))
    result = live.project_status(value, now=value["observed_at_unix"])
    assert result["window_sha256"] == expected_sha
    assert result["prior_checkpoint_sha256"] == parent["result"]["checkpoint_sha256"]
    assert (
        result["campaign_returned_tokens"]
        == parent["result"]["usage"]["campaign_returned_tokens"] + 6500
    )
    assert (
        result["start_decision"],
        result["end_decision"],
        result["response_limit"],
        result["campaign_returned_responses"],
    ) == (128, 256, 128, 193)
    assert result["source_result_url"] == parent["evidence_url"]
    assert "/" + live.DECLARATION_REVISION + "/" in result["declaration_url"]
    assert result["audited_result_url"] is None


def test_live_counts_remain_provisional_private_and_expiring(value):
    value.update(
        memory="private", owner_pid=123, account_id="private", new_save_verified=True
    )
    result = live.project_status(value, now=value["observed_at_unix"])
    assert result["campaign_elapsed_ticks_lower_bound"] == 51900
    assert (
        result["new_save_verified"] is False
        and result["source_checkpoint_verified"] is True
    )
    assert result["reported_charge_usd"] is None
    assert not {"memory", "owner_pid", "account_id", "controller_alive"} & result.keys()
    assert (
        live.project_status(value, now=value["observed_at_unix"] + 31)["status"]
        == "stale"
    )
    value.update(controller_alive=False, teardown_reported=True)
    assert (
        live.project_status(value, now=value["observed_at_unix"])["status"]
        == "controller_stopped"
    )
    value["observed_elapsed_ticks_lower_bound"] = None
    result = live.project_status(value, now=value["observed_at_unix"])
    assert result["new_elapsed_ticks_lower_bound"] is None
    assert result["campaign_elapsed_ticks_lower_bound"] == 51400


@pytest.mark.parametrize(
    "key,changed",
    [
        ("schema_version", "fortgym.public-matched-endurance-live/v1"),
        ("campaign_id", "unknown"),
        ("model", "gpt-5.6-sol"),
        ("replicate", True),
        ("start_decision", 64),
        ("end_decision", 128),
        ("prior_checkpoint_sha256", "f" * 64),
        ("window_sha256", "f" * 64),
        ("declaration_revision", "a" * 40),
        ("controller_source_sha256", "a" * 64),
        ("host_courier_sha256", "a" * 64),
        ("saved_elapsed_ticks_before_window", 0),
        ("returned_tokens_before_window", 0),
        ("controller_alive", None),
        ("responses", 129),
        ("responses", True),
        ("unsettled_claims", 64),
        ("returned_tokens", -1),
        ("returned_tokens", 2**53 - 1),
        ("observed_elapsed_ticks_lower_bound", 2**53 - 1),
        ("observed_elapsed_ticks_lower_bound", False),
        ("reported_charge_usd", 0),
        ("teardown_reported", True),
        ("observed_at_unix", 2**53),
    ],
)
def test_wrong_sources_and_counts_cannot_become_live_progress(value, key, changed):
    value[key] = changed
    with pytest.raises(ValueError):
        live.project_status(value, now=int(time.time()))


def test_audited_later_result_does_not_move_the_live_starting_baseline(
    value, monkeypatch
):
    data = deepcopy(live.keyboard_endurance_records())
    row = data["trials"][0]
    later = {
        "start_decision": 128,
        "next_decision": 256,
        "status": "completed",
        "execution": {"window_sha256": value["window_sha256"]},
    }
    url = (
        "https://github.com/lemoz/fort-gym/blob/" + "a" * 40 + "/synthetic-result.json"
    )
    row["windows"].append({"result": later, "evidence_url": url})
    row["latest_result"] = later
    monkeypatch.setattr(live, "keyboard_endurance_records", lambda: data)
    result = live.project_status(value, now=value["observed_at_unix"])
    assert (
        result["start_decision"] == 128
        and result["saved_elapsed_ticks_before_window"] == 51400
    )
    assert result["audited_result_url"] == url and result["new_save_verified"] is False


def test_bounded_file_route_preserves_v1_and_records_and_hides_error_paths(
    tmp_path, value, monkeypatch
):
    from fort_gym.bench.api import server

    assert (
        live.live_status(None)["status"]
        == live.live_status(tmp_path)["status"]
        == "not_connected"
    )
    monkeypatch.setattr(
        server,
        "get_settings",
        lambda: SimpleNamespace(FORT_GYM_PUBLIC_CAMPAIGN_DIR=str(tmp_path)),
    )
    client = TestClient(server.app)
    old_route = "/public/keyboard-cohort-endurance-active"
    records_route = "/public/keyboard-cohort-endurance-records"
    before = [client.get(path).json() for path in (old_route, records_route)]
    path = tmp_path / live.FILENAME
    path.write_text(json.dumps(value))
    route = "/public/keyboard-cohort-endurance-v2-active"
    response = client.get(route)
    assert (
        response.status_code == 200 and "no-store" in response.headers["cache-control"]
    )
    assert response.json()["campaign_returned_responses"] == 193
    assert before == [client.get(path).json() for path in (old_route, records_route)]
    path.write_text(" " * (live.MAX_BYTES + 1))
    response = client.get(route)
    assert response.status_code == 503 and str(tmp_path) not in response.text
    path.unlink()
    path.symlink_to(tmp_path / "absent")
    with pytest.raises(ValueError):
        live.live_status(tmp_path)


@pytest.mark.parametrize("audited", [False, True])
def test_longer_window_ui_keeps_baseline_and_expiry_and_links_audited_results(
    value, audited
):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    data = live.project_status(value, now=value["observed_at_unix"])
    if audited:
        data["status"] = "controller_stopped"
        data["audited_result_url"] = (
            "https://github.com/lemoz/fort-gym/blob/"
            + "a" * 40
            + "/synthetic-result.json"
        )
    program = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
class Element {
  constructor() { this.children=[]; this.events={}; }
  set textContent(v) { this.text=String(v); this.children=[]; }
  get textContent() { return (this.text||'')+this.children.map(n=>n.textContent).join(' '); }
  appendChild(v) { this.children.push(v); } replaceChildren(...v) { this.children=v; this.text=''; }
  addEventListener(k,v) { this.events[k]=v; }
}
const data=JSON.parse(process.argv[2]), nodes={}, timers=[]; let now=data.observed_at_unix*1000, fail=false;
class Clock extends Date { static now() { return now; } }
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'), {
  Date:Clock, document:{hidden:false,addEventListener(){},getElementById:id=>nodes[id]||=new Element(),createElement:()=>new Element()},
  fetch:async url=>{assert.equal(url,'/public/keyboard-cohort-endurance-v2-active');return {ok:!fail,json:async()=>data};},
  setInterval:fn=>timers.push(fn),setTimeout,clearTimeout,AbortController
});
(async()=>{
  await new Promise(setImmediate);
  const status=nodes['endurance-v2-live-status'], content=nodes['endurance-v2-live-content'];
  assert.match(nodes['endurance-v2-live-title'].textContent,/128 to 256/);
  assert.match(content.textContent,/51,400/); assert.match(content.textContent,/4,550,737/);
  assert.match(content.textContent,/65 \/ 128/); assert.match(content.textContent,/does not verify a new save/);
  if(data.audited_result_url) { assert.match(status.textContent,/Continuation recorded/); assert.match(content.textContent,/Read the verified result/); }
  else { assert.match(status.textContent,/continuation active/); }
  fail=true; await nodes['refresh-endurance-v2-live'].events.click();
  now+=31000; timers[0]();
  assert.doesNotMatch(status.textContent,/continuation active/);
  assert.match(status.textContent,data.audited_result_url?/Continuation recorded/:/stale/);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run(
        [
            node,
            "-e",
            program,
            str(PROJECT_ROOT / "web/static/campaign-endurance-live-v2.js"),
            json.dumps(data),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr

import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api import campaign_keyboard_records as records


def test_keyboard_endpoint_preserves_unknown_charges_and_separate_milestones():
    from fort_gym.bench.api.server import app

    client = TestClient(app)
    response = client.get("/public/keyboard-campaigns")
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    data = response.json()
    assert data == records.keyboard_campaign_records()
    assert data["live_tracking"] is False
    row = data["milestones"][0]
    assert row["progress"]["model_decisions"] == 8
    assert row["progress"]["elapsed_native_ticks"] == 6000
    assert row["usage"]["reported_charge_usd"] is None
    assert row["usage"]["all_attempt_tokens"] == 305806
    assert row["usage"]["campaign_tokens"] == 236802
    assert row["fortress_success"] == "not_assessed_in_public_operational_summary"
    assert "Astra Medium" in client.get("/campaigns").text
    assert client.get("/static/campaign-keyboard.js").status_code == 200


@pytest.fixture
def evidence_root(tmp_path):
    folder = tmp_path / "experiments/evidence"
    folder.mkdir(parents=True)
    for filename in records.PUBLISHED:
        shutil.copyfile(records.PROJECT_ROOT / "experiments/evidence" / filename, folder / filename)
    return tmp_path


def test_private_fields_and_unlisted_files_are_never_projected(evidence_root):
    path = evidence_root / "experiments/evidence" / records.PUBLISHED[0]
    value = json.loads(path.read_text())
    value["private_prompt"] = "secret-screen"
    value["campaign_result"]["map"] = "secret-map"
    value["usage"]["account_id"] = "secret-account"
    path.write_text(json.dumps(value))
    (path.parent / "private.json").write_text('{"token":"secret-token"}')
    assert "secret-" not in json.dumps(records.keyboard_campaign_records(evidence_root))


@pytest.mark.parametrize("mutation", ["zero", "tokens", "checkpoint", "teardown", "audit"])
def test_inconsistent_publications_are_rejected(evidence_root, mutation):
    path = evidence_root / "experiments/evidence" / records.PUBLISHED[0]
    value = json.loads(path.read_text())
    if mutation == "zero":
        value["usage"]["reported_charge_usd"] = 0
    elif mutation == "tokens":
        value["usage"]["total_tokens"] += 1
    elif mutation == "checkpoint":
        value["campaign_result"]["checkpoint_cursors"] = [4, 7]
    elif mutation == "teardown":
        value["attempts"][0]["teardown_verified"] = False
    else:
        value["campaign_result"]["independent_retained_evidence_audit_passed"] = False
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)


def test_missing_publication_is_not_empty_success(monkeypatch):
    from fort_gym.bench.api.server import app

    def missing():
        raise FileNotFoundError("private-path")

    monkeypatch.setattr(records, "keyboard_campaign_records", missing)
    response = TestClient(app).get("/public/keyboard-campaigns")
    assert response.status_code == 503
    assert "private-path" not in response.text


def test_keyboard_javascript_renders_recorded_usage_and_failure():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    program = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const helpers = require(process.argv[1]);
assert.equal(helpers.cost({cost_basis:'codex_subscription_charge_unreported/v1',
  reported_charge_usd:null}), 'Unreported · Codex subscription');
for (const value of [0, false, '', undefined, '0']) {
  assert.equal(helpers.cost({reported_charge_usd:value}), 'Unknown');
}
class Element {
  constructor() { this.children = []; this.events = {}; }
  set textContent(value) { this.text = String(value); }
  get textContent() { return (this.text || '') + this.children.map(x => x.textContent).join(' '); }
  append(value) { this.children.push(value); }
  replaceChildren() { this.children = []; }
  addEventListener(event, fn) { this.events[event] = fn; }
}
const elements = {};
const fakeDocument = {
  getElementById(id) { return elements[id] ||= new Element(); },
  createElement() { return new Element(); }
};
const data = JSON.parse(process.argv[2]);
let fail = false;
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  document: fakeDocument,
  fetch: async url => {
    assert.equal(url, '/public/keyboard-campaigns');
    return {ok: !fail, json: async () => data};
  }
});
(async () => {
  await new Promise(setImmediate);
  assert.equal(elements['keyboard-results'].hidden, false);
  assert.match(elements['keyboard-results'].textContent, /236,802 campaign tokens/);
  assert.match(elements['keyboard-results'].textContent, /305,806 including failed/);
  assert.match(elements['keyboard-results'].textContent, /Unreported/);
  assert.doesNotMatch(elements['keyboard-results'].textContent, /\$0/);
  assert.match(elements['keyboard-status'].textContent, /not a live activity/);
  fail = true;
  await elements['refresh-keyboard-campaigns'].events.click();
  assert.equal(elements['keyboard-results'].hidden, true);
  assert.equal(elements['refresh-keyboard-campaigns'].disabled, false);
  assert.match(elements['keyboard-status'].textContent, /could not be loaded/);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    subprocess.run(
        [
            node,
            "-e",
            program,
            str(records.PROJECT_ROOT / "web/static/campaign-keyboard.js"),
            json.dumps(records.keyboard_campaign_records()),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

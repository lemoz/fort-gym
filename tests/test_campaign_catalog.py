from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api.campaign_catalog import PROJECT_ROOT, campaign_catalog


def test_published_catalog_retains_real_failure_and_unrun_models():
    data = campaign_catalog()
    assert len(data["condition"]["models"]) == 3
    assert len(data["experiments"]) == 1
    record = data["experiments"][0]
    assert record["outcome"] == "model_action_contract_failure"
    assert record["last_observed_population"] == 7
    assert record["native_elapsed_ticks"] == 0
    assert record["reported_model_cost_usd"] == "0.003462525"
    assert record["dispatches_without_returned_usage"] == 3
    assert data["comparison_rankings_available"] is False
    assert data["live_tracking_available"] is False


@pytest.fixture
def catalog_root(tmp_path):
    for relative in (
        "experiments/campaigns/development_probe_v1.json",
        "experiments/evidence/development_glm_flash_20260906.json",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT_ROOT / relative, target)
    return tmp_path


def test_private_fields_and_unlisted_artifacts_are_not_published(catalog_root):
    path = catalog_root / "experiments/evidence/development_glm_flash_20260906.json"
    source = json.loads(path.read_text())
    source.update(private_path="/private/runtime", agent_memory="private-game-memory")
    path.write_text(json.dumps(source))
    (path.parent / "unlisted-private-result.json").write_text('{"secret": "do-not-publish"}')
    serialized = json.dumps(campaign_catalog(catalog_root))
    for private in ("private_path", "/private/runtime", "private-game-memory", "do-not-publish"):
        assert private not in serialized


def test_identity_mismatch_is_not_published(catalog_root):
    path = catalog_root / "experiments/evidence/development_glm_flash_20260906.json"
    source = json.loads(path.read_text())
    source["evidence_id"] = "other-attempt"
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError, match="declared condition"):
        campaign_catalog(catalog_root)


def test_campaign_http_routes_and_assets():
    from fort_gym.bench.api.server import app

    client = TestClient(app)
    page = client.get("/campaigns")
    assert page.status_code == 200 and "no-store" in page.headers["cache-control"]
    assert "Campaign experiments" in page.text
    assert "not a model ranking" in page.text
    assert "Published result: a workshop and five manufactured beds" in page.text
    assert "Earlier result: local model timeout" in page.text
    assert "Latest attempt: local model timeout" not in page.text
    response = client.get("/public/campaign-experiments")
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    assert response.json() == campaign_catalog()
    for asset in ("campaigns.js", "campaigns.css"):
        assert client.get(f"/static/{asset}").status_code == 200
    for page in ("landing.html", "results.html"):
        assert 'href="/campaigns"' in (PROJECT_ROOT / "web" / page).read_text()


def test_missing_catalog_is_service_error_not_empty_results(monkeypatch):
    from fort_gym.bench.api import server

    def missing():
        raise FileNotFoundError("private-path-must-not-leak")

    monkeypatch.setattr(server, "campaign_catalog", missing)
    response = TestClient(server.app).get("/public/campaign-experiments")
    assert response.status_code == 503
    assert response.json() == {"detail": "Campaign evidence is unavailable"}


def test_javascript_preserves_unknown_costs_and_model_coverage():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed")
    script = PROJECT_ROOT / "web/static/campaigns.js"
    subprocess.run(
        [
            node,
            "-e",
            """
const assert = require('node:assert/strict');
const helpers = require(process.argv[1]);
for (const value of [null, undefined, '', ' ', [], {}, false, true, NaN, Infinity, -1]) {
  assert.equal(helpers.money(value), 'Unknown');
}
assert.equal(helpers.money('0.003462525'), '$0.003463');
assert.equal(helpers.money(0), '$0.000000');
assert.equal(helpers.number(null), 'Unknown');
assert.equal(helpers.number(false), 'Unknown');
assert.equal(helpers.number(0), '0');
assert.deepEqual(helpers.modelCoverage({condition:{models:['a','b']},experiments:[{model:'a'}]}),
  [{model:'a',attempts:1},{model:'b',attempts:0}]);
""",
            str(script),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_javascript_renders_evidence_and_reports_network_failure():
    """Execute frontend control flow with an in-memory document test double."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed")
    subprocess.run(
        [
            node,
            "-e",
            """
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; }
  set textContent(value) { this.text = String(value); }
  get textContent() { return (this.text || '') + this.children.map(x => x.textContent).join(' '); }
  append(value) { this.children.push(value); }
  replaceChildren() { this.children = []; }
  addEventListener(event, callback) { this.events[event] = callback; }
}
const elements = {};
const document = {
  getElementById(id) { return elements[id] ||= new Element('div'); },
  createElement(tag) { return new Element(tag); }
};
let fail = false;
const data = JSON.parse(process.argv[2]);
// Adversarial text must remain text, not become markup or a source URL.
data.experiments[0].model = '<img src=x onerror=alert(1)>';
data.experiments[0].code_revision = 'javascript:alert(1)';
const fetch = async url => {
  assert.equal(url, '/public/campaign-experiments');
  return { ok: !fail, json: async () => data };
};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), { document, fetch });
(async () => {
  await new Promise(setImmediate);
  assert.equal(elements['catalog-content'].hidden, false);
  assert.equal(elements['experiment-rows'].children.length, 1);
  const row = elements['experiment-rows'].children[0];
  assert.equal(row.children[0].text, '<img src=x onerror=alert(1)>');
  assert.equal(row.children[2].textContent, '0');
  assert.equal(row.children[3].textContent, '7');
  assert.match(row.children[4].textContent, /0.003463/);
  const details = elements['experiment-details'].children[0];
  assert.equal(details.children.some(child => child.href?.startsWith('javascript:')), false);
  row.children[0].children[0].events.click();
  assert.equal(details.open, true);
  fail = true;
  await elements['refresh-campaigns'].events.click();
  assert.equal(elements['catalog-content'].hidden, true);
  assert.equal(elements['refresh-campaigns'].disabled, false);
  assert.match(elements['catalog-status'].textContent, /could not be loaded/);
})().catch(error => { console.error(error); process.exitCode = 1; });
""",
            str(PROJECT_ROOT / "web/static/campaigns.js"),
            json.dumps(campaign_catalog()),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

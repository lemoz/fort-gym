import hashlib
import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api import keyboard_cohort as cohort


def test_actual_recorded_trials_and_three_unpublished_slots():
    data = cohort.keyboard_cohort()
    assert data["recorded_trials"] == 3 and data["declared_trials"] == 6
    assert data["matched_initial_windows_complete"] is False
    assert data["strong_ranking_supported"] is False
    assert data["live_owner_status_included"] is False
    assert [r["model"] for r in data["trials"]] == [
        "gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-6-astra"
    ]
    for row in data["trials"][3:]:
        assert row["result"] is None and row["publication_state"] == "no_published_result"
        assert row["evidence_url"] is None
    result = data["trials"][0]["result"]
    assert result["responses"] == result["response_limit"] == 32
    assert result["saved_elapsed_ticks"] == 11200
    assert result["saved_metrics"]["population"] == 7
    assert result["saved_metrics"]["completed_workshops"] == 1
    assert result["saved_metrics"]["completed_farms"] == 1
    assert result["saved_metrics"]["completed_beds"] == 0
    assert result["usage"]["returned_tokens"] == 1043596
    assert result["usage"]["reported_charge_usd"] is None
    assert result["production_rates"] is None and result["consumption_rates"] is None
    assert result["year_two_reached"] is False and result["sustainability_established"] is False
    assert result["final_fresh_reload_verified"] is False
    assert result["shutdown"]["guest_command_warning"] is True
    assert result["shutdown"]["vm_observed_stopped"] is True
    assert result["resources"]["memory_peak_bytes"] == 1237028864
    assert result["resources"]["oom_kills"] == 0
    assert result["timeline"][-1]["elapsed_ticks"] == result["saved_elapsed_ticks"]
    assert [p["decision"] for p in result["timeline"]] == list(range(1, 33))
    assert result["timeline"][-1]["metrics"] == result["saved_metrics"]
    sol = data["trials"][1]["result"]
    assert sol["responses"] == 32 and sol["saved_elapsed_ticks"] == 2500
    assert sol["saved_metrics"]["population"] == 7
    assert sol["saved_metrics"]["completed_workshops"] == 0
    assert sol["saved_metrics"]["completed_farms"] == 0
    assert sol["usage"]["returned_tokens"] == 792764
    assert sol["usage"]["reported_charge_usd"] is None
    assert sol["shutdown"]["guest_command_warning"] is False
    assert sol["timeline"][-1]["metrics"] == sol["saved_metrics"]
    assert sol["timeline"][-1]["elapsed_ticks"] == 2500
    terra = data["trials"][2]["result"]
    assert terra["responses"] == 32 and terra["saved_elapsed_ticks"] == 7000
    assert terra["usage"]["returned_tokens"] == 859063
    assert terra["saved_metrics"]["population"] == 7
    assert terra["saved_metrics"]["completed_workshops"] == 0
    assert terra["saved_metrics"]["completed_beds"] == 0
    assert terra["saved_metrics"]["completed_farms"] == 0
    assert terra["timeline"][-1]["metrics"] == terra["saved_metrics"]
    assert terra["storage_amendment"] == cohort.STORAGE_AMENDMENT
    assert data["identical_host_configuration"] is False
    assert data["wall_clock_performance_comparison_supported"] is False
    serialized = json.dumps(data)
    for private in ("/Users/", "/evidence/astra", '"account_id":', '"prompt_text":',
                    '"screen_text":', '"api_key":'):
        assert private not in serialized


@pytest.mark.parametrize("index,model", [(0, "astra"), (1, "sol"), (2, "terra")])
def test_declared_conditions_and_source_are_bound(index, model):
    result = cohort.keyboard_cohort()["trials"][index]["result"]
    path = cohort.PROJECT_ROOT / "experiments/keyboard_matched_pilot_20260910"
    for kind in ("condition", "trial"):
        digest = hashlib.sha256((path / f"{model}-{kind}.json").read_bytes()).hexdigest()
        assert digest == result["execution"][f"{kind}_file_sha256"]
    assert result["execution"]["source_revision"] == cohort.PLAN_REVISION
    assert result["reasoning_effort"] == "medium"
    assert result["screen_size"] == [120, 40]
    assert result["inherited_usage"] is False and result["initial_memory_empty"] is True


@pytest.mark.parametrize("field", ["image_id", "source_revision", "binding_sha256", "screen_size", "prompt_profile", "reasoning_effort"])
def test_different_execution_or_controls_are_not_silently_compared(monkeypatch, field):
    actual_read = cohort._read
    def altered_read(path, digest):
        value = actual_read(path, digest)
        if value.get("model") == "gpt-5.6-sol":
            target = value["execution"] if field in value["execution"] else value
            target[field] = "different"
        return value
    monkeypatch.setattr(cohort, "_read", altered_read)
    with pytest.raises(ValueError, match="matching condition"):
        cohort.keyboard_cohort()


@pytest.fixture
def copied_evidence(tmp_path, monkeypatch):
    for relative in [cohort.PLAN_PATH, *[v[0] for v in cohort.RESULTS.values()]]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cohort.PROJECT_ROOT / relative, target)
    monkeypatch.setattr(cohort, "PROJECT_ROOT", tmp_path)
    return tmp_path


@pytest.mark.parametrize("mutation", ["missing", "tampered", "private", "oversized", "symlink"])
def test_missing_or_changed_public_evidence_fails_closed(copied_evidence, mutation):
    path = copied_evidence / next(iter(cohort.RESULTS.values()))[0]
    if mutation == "missing":
        path.unlink()
    elif mutation == "tampered":
        path.write_text('{}')
    elif mutation == "private":
        value = json.loads(path.read_text())
        value["private_prompt"] = "secret"
        path.write_text(json.dumps(value))
    elif mutation == "oversized":
        path.write_text(' ' * 131073)
    else:
        source = path.with_suffix('.copy')
        path.rename(source)
        path.symlink_to(source)
    with pytest.raises(ValueError):
        cohort.keyboard_cohort()
    from fort_gym.bench.api.server import app
    response = TestClient(app).get('/public/keyboard-cohort')
    assert response.status_code == 503
    assert response.json() == {"detail": "Matched trial evidence is unavailable"}


def test_endpoint_and_page_preserve_existing_keyboard_surfaces():
    from fort_gym.bench.api.server import app
    client = TestClient(app)
    response = client.get('/public/keyboard-cohort')
    assert response.status_code == 200
    assert 'no-store' in response.headers['cache-control']
    assert response.json() == cohort.keyboard_cohort()
    page = client.get('/campaigns').text
    assert 'Matched model trials' in page and 'Live native run' in page
    assert '/static/campaign-matched.js?v=1' in page
    assert client.get('/static/campaign-matched.js').status_code == 200
    assert client.get('/public/keyboard-campaigns').status_code == 200
    assert client.get('/public/keyboard-admission').status_code == 200


def test_javascript_renders_history_unknowns_and_failed_refresh():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node unavailable')
    program = r'''
const assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.hidden = true; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return (this.text || '') + this.children.map(x => x.textContent).join(' '); }
  appendChild(value) { this.children.push(value); }
  replaceChildren(...values) { this.children = values; this.text = ''; }
  setAttribute(key, value) { this[key] = value; }
  addEventListener(event, fn) { this.events[event] = fn; }
}
const nodes = {}, data = JSON.parse(process.argv[2]); let fail = false;
data.trials[0].result.timeline[0].metrics.drink_stock = null;
const document = {getElementById: id => nodes[id] ||= new Element('div'), createElement: tag => new Element(tag)};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  document, fetch: async url => {
    assert.equal(url, '/public/keyboard-cohort');
    return {ok: !fail, json: async () => data};
  }
});
(async () => {
  await new Promise(setImmediate);
  const result = nodes['keyboard-cohort-content'];
  assert.equal(result.hidden, false);
  assert.match(nodes['keyboard-cohort-status'].textContent, /3 of 6/);
  assert.match(result.textContent, /11,200/);
  assert.match(result.textContent, /1,043,596/);
  assert.match(result.textContent, /792,764/);
  assert.match(result.textContent, /2,500/);
  assert.match(result.textContent, /7,000/);
  assert.match(result.textContent, /859,063/);
  assert.match(result.textContent, /32 GiB · amended/);
  assert.match(result.textContent, /wall-clock speed is not compared/);
  assert.match(result.textContent, /unreported, not \$0/);
  assert.match(result.textContent, /Unknown/);
  assert.match(result.textContent, /No published result/);
  assert.match(result.textContent, /Window complete; continuation pending/);
  assert.match(result.textContent, /Guest shutdown command returned a warning/);
  const all = []; const walk = n => { all.push(n); n.children.forEach(walk); }; walk(result);
  assert.equal(all.filter(n => n.tag === 'tbody')[0].children.length, 6);
  assert.equal(all.filter(n => n.tag === 'tbody')[1].children.length, 32);
  assert.equal(all.filter(n => n.tag === 'tbody')[2].children.length, 32);
  assert.equal(all.filter(n => n.tag === 'tbody')[3].children.length, 32);
  assert.equal(all.find(n => n.tag === 'a').href, data.trials[0].evidence_url);
  const previous = result.textContent; fail = true;
  await nodes['refresh-keyboard-cohort'].events.click();
  assert.equal(result.textContent, previous);
  assert.match(nodes['keyboard-cohort-status'].textContent, /previously loaded/);
  assert.equal(nodes['refresh-keyboard-cohort'].disabled, false);
  result.hidden = true;
  await nodes['refresh-keyboard-cohort'].events.click();
  assert.match(nodes['keyboard-cohort-status'].textContent, /unavailable/);
})().catch(e => { console.error(e); process.exitCode = 1; });
'''
    result = subprocess.run(
        [node, '-e', program, str(cohort.PROJECT_ROOT / 'web/static/campaign-matched.js'),
         json.dumps(cohort.keyboard_cohort())], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr

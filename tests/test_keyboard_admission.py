"""Admission pauses are sealed operational records, never inferred game outcomes."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api import keyboard_admission as admission
from tests.test_campaign_keyboard_records import evidence_root as evidence_root


@pytest.fixture
def publication(evidence_root):
    path = evidence_root / "experiments/evidence" / admission.PUBLISHED
    shutil.copyfile(admission.PROJECT_ROOT / "experiments/evidence" / admission.PUBLISHED, path)
    return path, json.loads(path.read_bytes())


def test_actual_pause_preserves_the_full_saved_parent():
    data = admission.admission_record()
    assert data["checkpoint_cursor"] == 903 and data["saved_elapsed_ticks"] == 268582
    assert data["campaign_responses"] == 1085 and data["campaign_tokens"] == 34521087
    assert data["all_attempt_tokens"] == 34590091
    assert data["recorded_only"] is True and data["vm_started"] is False
    assert data["fresh_checkpoint_load_verified"] is False
    assert data["new_model_calls"] == data["new_tokens"] == data["new_game_ticks"] == 0
    assert data["reported_charge_usd"] is None


@pytest.mark.parametrize("key,value", [
    ("schema_version", "v2"), ("status", "completed"), ("reason", "game_failed"),
    ("phase", "after_vm_start"), ("model", "different-model"), ("reasoning_effort", "high"),
    ("new_model_calls", 1), ("new_model_calls", False), ("new_tokens", -1),
    ("new_game_ticks", 1), ("vm_started", True), ("vm_started", 0),
    ("game_started", True), ("cloud_vms_created", 1), ("checkpoint_unchanged", False),
    ("api_fallback_used", True), ("usage_reset_used", True),
    ("checkpoint_cursor", 902), ("checkpoint_cursor", True), ("saved_elapsed_ticks", 0),
    ("campaign_responses", 0), ("campaign_tokens", 34521088), ("all_attempt_tokens", 0),
    ("checkpoint_sha256", "a" * 64), ("parent_record", "missing"),
    ("fresh_checkpoint_load_verified", True), ("independent_audit_passed", False),
    ("reported_charge_usd", 0), ("source_revision", "no"),
    ("independent_audit_sha256", None), ("condition_sha256", []), ("window_sha256", "bad"),
    ("run_id", "<script>secret</script>"),
])
def test_pause_cannot_hide_work_or_alter_parent(evidence_root, publication, key, value):
    path, source = publication
    source[key] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        admission.admission_record(evidence_root)


def test_account_details_and_private_evidence_never_pass_through(evidence_root, publication):
    path, source = publication
    source.update(account_id="secret-account", windows=["secret-quota"],
                  private_prompt="secret-prompt", private_path="secret-path", resets_at_unix=1234)
    path.write_text(json.dumps(source))
    data = admission.admission_record(evidence_root)
    assert "secret-" not in json.dumps(data)
    assert all(key not in data for key in ("windows", "resets_at_unix", "private_path"))


@pytest.mark.parametrize("kind", ["missing", "symlink", "oversize", "nonobject"])
def test_unsafe_or_missing_record_is_not_a_success(evidence_root, publication, kind):
    path, source = publication
    if kind in ("missing", "symlink"):
        path.unlink()
        if kind == "symlink":
            target = path.parent / "private-copy.json"
            target.write_text(json.dumps(source))
            path.symlink_to(target)
    else:
        path.write_text(" " * 65537 if kind == "oversize" else "[]")
    with pytest.raises(ValueError):
        admission.admission_record(evidence_root)


def test_endpoint_is_uncached_and_hides_private_error_details(monkeypatch):
    from fort_gym.bench.api.server import app
    client = TestClient(app)
    response = client.get("/public/keyboard-admission")
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert response.json() == admission.admission_record()
    def missing():
        raise FileNotFoundError("secret-path")
    monkeypatch.setattr(admission, "admission_record", missing)
    response = client.get("/public/keyboard-admission")
    assert response.status_code == 503 and "secret-path" not in response.text


@pytest.mark.parametrize("case", ["valid", "started", "paid", "unavailable"])
def test_recorded_pause_renders_without_claiming_live_quota_or_gameplay(case):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable")
    data = admission.admission_record()
    if case == "started":
        data["vm_started"] = True
    if case == "paid":
        data["api_fallback_used"] = True
    program = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
class Element {
  constructor() { this.children = []; this.events = {}; this.hidden = true; }
  append(value) { this.children.push(value); }
  replaceChildren() { this.children = []; }
  set textContent(value) { this.text = value; }
  get textContent() { return (this.text || '') + this.children.map(x => x.textContent).join(' '); }
  addEventListener(name, value) { this.events[name] = value; }
}
const box = new Element(), button = new Element();
const data = JSON.parse(process.argv[2]), scenario = process.argv[3];
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  document: {getElementById: id => id === 'keyboard-admission' ? box : button,
    createElement: () => new Element(), addEventListener: () => {}},
  AbortController, setTimeout, clearTimeout,
  fetch: async url => { assert.equal(url, '/public/keyboard-admission');
    return {ok: scenario !== 'unavailable', json: async () => data}; }
});
(async () => {
  await new Promise(setImmediate);
  assert.equal(box.hidden, false);
  if (scenario === 'valid') {
    assert.match(box.textContent, /Recorded launch pause/);
    assert.match(box.textContent, /checkpoint 903/);
    assert.match(box.textContent, /0 model calls/);
    assert.match(box.textContent, /not a live account-quota reading/);
    assert.match(box.textContent, /not a gameplay failure or a dollar-budget overrun/);
    assert.doesNotMatch(box.textContent, /90%|secret|year.two success/i);
  } else {
    assert.match(box.textContent, /Recorded launch status is unavailable/);
    assert.doesNotMatch(box.textContent, /0 model calls/);
  }
  assert.equal(typeof button.events.click, 'function');
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    script = Path(admission.PROJECT_ROOT) / "web/static/campaign-keyboard-admission.js"
    subprocess.run([node, "-e", program, str(script), json.dumps(data), case],
                   check=True, capture_output=True, text=True, timeout=10)

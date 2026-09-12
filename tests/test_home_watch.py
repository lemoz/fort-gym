import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.agent.keyboard_exchange import digest
from fort_gym.bench.api.watch import (
    FILENAME,
    SCHEMA,
    action_projection,
    live_status,
    project_live,
    screen_projection,
)
from scripts.campaign_watch_observe import publish, snapshot
from scripts.export_home_recording import export

ROOT = Path(__file__).resolve().parents[1]


def test_export_binds_the_trace_and_request_to_the_exact_audit(tmp_path):
    folder = tmp_path / "model/one"
    folder.mkdir(parents=True)
    action = {
        "type": "KEYSTROKE",
        "params": {"keys": ["q"]},
        "advance_ticks": 0,
        "intent": "Inspect",
        "memory_update": "private",
    }
    request = {
        "request_id": "one",
        "model": "gpt-6-astra",
        "control_profile": "native_keyboard/v2",
        "screen": {
            "width": 1,
            "height": 1,
            "tile_order": "column_major",
            "tiles": [[219, 7, 0]],
        },
    }
    for name, data in [
        ("request", request),
        ("summary", {"decision_index": 0, "request_id": "one"}),
        ("response", {"request_sha256": digest(request), "result": {"action": action}}),
    ]:
        (folder / (name + ".json")).write_text(json.dumps(data))
    relative = "evidence/astra/segment-0/checkpoint/trace.jsonl"
    trace = tmp_path / relative
    trace.parent.mkdir(parents=True)
    row = {
        "step": 0,
        "action": action,
        "execute": {"accepted": True},
        "tick_advance": {"start_year": 30, "start_tick": 0, "ticks_advanced": 0},
        "state_after_advance": {"year": 30, "year_tick": 0, "population": 7},
    }
    trace.write_text(json.dumps(row) + "\n")
    audit = {
        "passed": True,
        "first_step": 0,
        "source_revision": "a" * 40,
        "sources": {relative: hashlib.sha256(trace.read_bytes()).hexdigest()},
        "receipt_reviews": [{"decision_index": 0, "request_sha256": digest(request)}],
    }
    audit_path = tmp_path / "review.json"
    audit_path.write_text(json.dumps(audit))
    audit_sha = hashlib.sha256(audit_path.read_bytes()).hexdigest()
    output = export(
        tmp_path, audit_path, audit_sha, identity="fixture", title="Fixture"
    )
    assert output["frames"][0]["after"]["population"] == 7
    assert "memory" not in json.dumps(output)
    with pytest.raises(ValueError, match="Audit digest differs"):
        export(tmp_path, audit_path, "b" * 64, identity="fixture", title="Fixture")
    original = trace.read_bytes()
    row["state_after_advance"]["population"] = 99
    trace.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="trace differs"):
        export(tmp_path, audit_path, audit_sha, identity="fixture", title="Fixture")
    trace.write_bytes(original)
    request["screen"]["tiles"] = [[1, 7, 0]]
    (folder / "request.json").write_text(json.dumps(request))
    with pytest.raises(ValueError, match="do not match"):
        export(tmp_path, audit_path, audit_sha, identity="fixture", title="Fixture")


@pytest.fixture
def screen():
    return {
        "width": 2,
        "height": 2,
        "tile_order": "column_major",
        "tiles": [[219, 7, 0], [219, 7, 0], [1, 15, 0], [32, 0, 1]],
    }


@pytest.fixture
def value(screen):
    return {
        "schema_version": SCHEMA,
        "owner_alive": True,
        "observed_at_unix": 1000,
        "run_id": "watch-fixture",
        "model": "gpt-6-astra",
        "frame": {
            "decision": 97,
            "captured_at_unix": 990,
            "screen": screen_projection(screen),
            "action": {
                "intent": "Open the workshop.",
                "keys": ["q"],
                "advance_ticks": 0,
            },
            "action_status": "chosen_not_execution_verified",
        },
    }


def test_spectator_projection_preserves_screen_and_strips_private_fields(value):
    value.update(memory="private", private_prompt="secret", owner_pid=123)
    value["frame"]["action"]["memory_update"] = "never publish"
    result = project_live(value, now=1005)
    assert result["status"] == "running"
    assert result["frame"]["screen"]["runs"][0] == [2, 219, 7, 0]
    assert result["frame"]["action_status"] == "chosen_not_execution_verified"
    assert "private" not in json.dumps(result) and "memory" not in json.dumps(result)
    assert "owner" not in json.dumps(result)
    assert project_live(value, now=1031)["status"] == "stale"
    value["owner_alive"] = False
    assert project_live(value, now=1005)["status"] == "stopped"


@pytest.mark.parametrize(
    "change",
    [
        {"owner_alive": 1},
        {"observed_at_unix": True},
        {"observed_at_unix": 1006},
        {"run_id": "../secrets"},
        {"schema_version": "other"},
    ],
)
def test_spectator_rejects_invalid_identity_and_time(value, change):
    value.update(change)
    with pytest.raises(ValueError):
        project_live(value, now=1000)


def test_compressed_screen_is_bounded(value):
    value["frame"]["screen"]["runs"][0][0] = 999999
    with pytest.raises(ValueError):
        project_live(value, now=1000)


def test_live_action_cannot_be_claimed_executed(value):
    value["frame"]["action_status"] = "executed"
    with pytest.raises(ValueError):
        project_live(value, now=1000)


def test_live_api_is_no_store_and_never_exposes_source_errors(
    tmp_path, value, monkeypatch
):
    from fort_gym.bench.api import server

    monkeypatch.setattr(
        server,
        "get_settings",
        lambda: SimpleNamespace(FORT_GYM_PUBLIC_CAMPAIGN_DIR=str(tmp_path)),
    )
    client = TestClient(server.app)
    assert client.get("/public/watch-active").json()["status"] == "not_connected"
    publish(tmp_path, value)
    response = client.get("/public/watch-active")
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert response.json()["status"] == "stale"
    (tmp_path / FILENAME).write_text("private broken data")
    response = client.get("/public/watch-active")
    assert response.status_code == 503
    assert "private" not in response.text and str(tmp_path) not in response.text
    (tmp_path / FILENAME).unlink()
    (tmp_path / FILENAME).symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError):
        live_status(tmp_path)


def test_action_projection_does_not_include_memory():
    value = {
        "type": "KEYSTROKE",
        "params": {"keys": [" "]},
        "advance_ticks": 20,
        "intent": "Continue work",
        "memory_update": "private",
    }
    assert action_projection(value) == {
        "keys": [" "],
        "advance_ticks": 20,
        "intent": "Continue work",
    }


def test_observer_uses_completed_matching_receipts_without_game_calls(tmp_path, screen):
    folder = tmp_path / "model/one"
    folder.mkdir(parents=True)
    request = {
        "request_id": "one",
        "model": "gpt-6-astra",
        "screen": screen,
        "memory": "secret",
    }
    response = {
        "request_sha256": digest(request),
        "result": {
            "action_grammar_valid": True,
            "action": {
                "type": "KEYSTROKE",
                "params": {"keys": ["q"]},
                "advance_ticks": 0,
                "intent": "Inspect a workshop",
                "memory_update": "private",
            },
        },
    }
    for name, data in [
        ("request", request),
        ("response", response),
        ("summary", {"decision_index": 0, "request_id": "one"}),
    ]:
        (folder / (name + ".json")).write_text(json.dumps(data))
    import time

    now = int(time.time())
    base = {"run_id": "test", "model": "gpt-6-astra", "saved_checkpoint_cursor": 96}
    result = snapshot(tmp_path, base, alive=True, now=now)
    assert result["frame"]["decision"] == 97
    assert result["frame"]["action_status"] == "chosen_not_execution_verified"
    assert "secret" not in json.dumps(result) and "memory" not in json.dumps(result)
    response["request_sha256"] = "a" * 64
    (folder / "response.json").write_text(json.dumps(response))
    with pytest.raises(ValueError):
        snapshot(tmp_path, base, alive=True, now=now)


def test_published_recordings_are_bounded_hashed_allowlisted_and_consecutive():
    root = ROOT / "web/static/recordings"
    catalog = json.loads((root / "catalog.json").read_text())
    assert len(catalog["recordings"]) == 14
    total = 0
    for row in catalog["recordings"]:
        path = root / (row["id"] + ".json")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
        recording = json.loads(path.read_text())
        assert recording["audit_sha256"] == row["audit_sha256"]
        frames = recording["frames"]
        assert [frame["decision"] for frame in frames] == list(
            range(recording["first_decision"], recording["last_decision"] + 1)
        )
        for frame in frames:
            assert set(frame) == {
                "decision",
                "screen",
                "action",
                "accepted",
                "before",
                "after",
            }
            assert set(frame["action"]) == {"intent", "keys", "advance_ticks"}
            assert len(frame["action"]["intent"]) <= 2000
            assert set(frame["screen"]) == {"width", "height", "tile_order", "runs"}
        total += len(frames)
    assert total == 1056
    astra = json.loads((root / "astra-97-256.json").read_text())
    assert astra["saved_through_decision"] == 224 and astra["last_decision"] == 256
    terra = json.loads((root / "terra-65-128.json").read_text())
    assert terra["frames"][4]["accepted"] is False


def test_homepage_spectator_precedes_marketing_and_uses_only_read_endpoints():
    html = (ROOT / "web/landing.html").read_text()
    assert html.index('id="watch-root"') < html.index('class="home-hero"')
    assert "/static/home-watch.mjs" in html
    script = (ROOT / "web/static/home-watch.mjs").read_text()
    model = (ROOT / "web/static/home-watch-model.mjs").read_text()
    assert "readLiveStatus" in script and "/public/watch-active" in model
    assert "/static/recordings/" in script
    for source in (script, model):
        assert "/screenshot" not in source and "/admin" not in source
        assert "memory_update" not in source and "innerHTML" not in source


def test_home_watch_javascript_contracts():
    subprocess.run(
        ["node", "--test", str(ROOT / "tests/home_watch_client.mjs")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_optional_spectator_failure_does_not_stop_counter_publication(
    tmp_path, monkeypatch, capsys
):
    import sys
    from scripts import campaign_keyboard_observe as observer
    from scripts import campaign_watch_observe as watch

    run = tmp_path / "run"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "observe",
            "--run-dir",
            str(run),
            "--condition",
            "condition",
            "--window",
            "window",
            "--public-dir",
            str(tmp_path / "public"),
            "--owner-pid",
            "123",
            "--historical-failed-delivery-tokens",
            "0",
            "--publish-watch",
        ],
    )
    identities = iter(["python -u run/operator.py", None])
    monkeypatch.setattr(observer, "owner_identity", lambda _: next(identities))
    monkeypatch.setattr(observer, "baseline", lambda *args: {})
    monkeypatch.setattr(
        observer, "snapshot", lambda *args, **kwargs: {"new_responses": 0}
    )
    published = []
    monkeypatch.setattr(
        observer, "publish_status", lambda *args: published.append(args)
    )

    def unavailable(*args, **kwargs):
        raise ValueError("private source details")

    monkeypatch.setattr(watch, "snapshot", unavailable)
    observer.main()
    assert len(published) == 1
    output = capsys.readouterr().out
    assert '"watch_status": "unavailable"' in output
    assert "private" not in output

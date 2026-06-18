from __future__ import annotations

from fort_gym.bench import cli


def test_run_api_agent_sends_preserve_save(monkeypatch):
    calls = []

    def fake_json_request(**kwargs):
        calls.append(kwargs)
        if kwargs["method"] == "POST":
            return {"id": "run-preserve", "status": "running"}
        return {"id": "run-preserve", "status": "completed", "score": 42.0}

    monkeypatch.setattr(cli, "_json_request", fake_json_request)
    monkeypatch.setattr(cli, "_find_public_run", lambda _base_url, _run_id: {"token": "tok"})
    monkeypatch.setattr(cli, "_load_trace_records", lambda _run_id, _dir: ([], "/tmp/trace.jsonl"))
    monkeypatch.setattr(cli, "_load_summary", lambda _run_id, _dir: ({}, "/tmp/summary.json"))

    result = cli._run_api_agent(
        api_base_url="http://api.test",
        public_base_url="http://public.test",
        admin_user="admin",
        admin_password="pw",
        model="anthropic-keystroke",
        backend="dfhack",
        max_steps=2,
        ticks_per_step=500,
        server_artifacts_dir="/tmp/artifacts",
        poll_interval=0,
        timeout_seconds=1,
        preserve_save=True,
    )

    assert calls[0]["payload"]["preserve_save"] is True
    assert result["preserve_save"] is True


def test_write_live_agent_packet(tmp_path):
    report = {
        "ok": True,
        "comparison": {
            "baseline_score": 23.5,
            "model_score": 26.0,
            "score_delta": 2.5,
            "result": "model_higher",
        },
        "runs": {
            "baseline": {
                "run_id": "baseline-run",
                "model": "fake",
                "status": "completed",
                "score": 23.5,
                "public_run_url": "http://example.test/public/runs/base",
                "public_replay_url": "http://example.test/public/runs/base/events/replay",
                "public_trace_url": "http://example.test/public/runs/base/export/trace",
                "trace": "/tmp/base/trace.jsonl",
                "summary": "/tmp/base/summary.json",
                "actions": [
                    {
                        "step": 0,
                        "type": "DIG",
                        "ticks_advanced": 0,
                        "score": 23.5,
                        "intent": "baseline dig",
                    }
                ],
            },
            "model": {
                "run_id": "model-run",
                "model": "anthropic-keystroke",
                "status": "completed",
                "score": 26.0,
                "public_run_url": "http://example.test/public/runs/model",
                "public_replay_url": "http://example.test/public/runs/model/events/replay",
                "public_trace_url": "http://example.test/public/runs/model/export/trace",
                "trace": "/tmp/model/trace.jsonl",
                "summary": "/tmp/model/summary.json",
                "actions": [
                    {
                        "step": 0,
                        "type": "KEYSTROKE",
                        "ticks_advanced": 200,
                        "score": 26.0,
                        "intent": "starter dig",
                    }
                ],
            },
        },
    }

    packet = cli._write_live_agent_packet(
        report=report,
        packet_path=None,
        server_artifacts_dir=str(tmp_path),
    )

    text = packet.read_text(encoding="utf-8")
    assert packet == tmp_path / "model-run" / "live_agent_report.md"
    assert "Status: PASS" in text
    assert "Result: `model_higher`" in text
    assert "Score delta: `2.5`" in text
    assert "http://example.test/public/runs/model/events/replay" in text
    assert "step 0: KEYSTROKE ticks=200 score=26.0" in text


def test_diagnose_actions_flags_live_blockers():
    diagnostics = cli._diagnose_actions(
        [
            {
                "type": "KEYSTROKE",
                "params": {"keys": ["STRING_A122"]},
                "valid": True,
                "accepted": True,
                "ticks_advanced": 0,
            },
            {
                "type": "KEYSTROKE",
                "params": {"keys": ["D_DESIGNATE", "DESIGNATE_DIG"]},
                "valid": True,
                "accepted": True,
                "ticks_advanced": 0,
            },
        ],
        {"duration_ticks": 0},
    )

    assert diagnostics["accepted_actions"] == 2
    assert diagnostics["designation_attempts"] == 1
    assert diagnostics["status_menu_actions"] == 1
    assert diagnostics["ticks_advanced"] == 0
    assert diagnostics["blockers"] == [
        "designation_without_time",
        "status_menu_exploration",
    ]


def test_diagnose_actions_flags_tick_only_work_score():
    diagnostics = cli._diagnose_actions(
        [
            {
                "type": "WAIT",
                "valid": True,
                "accepted": True,
                "ticks_advanced": 500,
            }
        ],
        {
            "duration_ticks": 500,
            "work_score": 0.0,
            "work_progress": 0,
            "target_floor_tiles_delta": 0,
            "target_wall_tiles_delta": 0,
        },
    )

    assert "no_dig_designation" in diagnostics["blockers"]
    assert "tick_only_score" in diagnostics["blockers"]
    assert diagnostics["work_progress"] == 0
    assert diagnostics["work_score"] == 0.0


def test_diagnose_actions_flags_completed_room_without_utility():
    diagnostics = cli._diagnose_actions(
        [
            {
                "type": "DIG",
                "valid": True,
                "accepted": True,
                "ticks_advanced": 500,
            },
            {
                "type": "WAIT",
                "valid": True,
                "accepted": True,
                "ticks_advanced": 500,
            },
        ],
        {
            "duration_ticks": 1000,
            "work_score": 10.0,
            "completion_score": 10.0,
            "utility_score": 0.0,
            "production_score": 0.0,
            "work_progress": 25,
            "completion_progress": 25,
            "utility_progress": 0,
            "production_progress": 0,
        },
    )

    assert "completed_room_without_utility_action" in diagnostics["blockers"]
    assert "completed_room_without_utility_progress" in diagnostics["blockers"]
    assert "completed_room_without_production_action" in diagnostics["blockers"]
    assert "completed_room_without_production_progress" in diagnostics["blockers"]
    assert diagnostics["utility_progress"] == 0
    assert diagnostics["utility_score"] == 0.0
    assert diagnostics["production_progress"] == 0
    assert diagnostics["production_score"] == 0.0


def test_write_live_agent_suite_artifacts(tmp_path):
    baseline_runs = [
            {
                "trial": 1,
                "model": "fake",
                "status": "completed",
                "score": 23.5,
                "work_score": 0.0,
                "completion_score": 0.0,
                "utility_score": 0.0,
                "production_score": 0.0,
                "work_progress": 0,
                "completion_progress": 0,
                "utility_progress": 0,
                "production_progress": 0,
                "public_run_url": "http://example.test/base-1",
                "public_replay_url": "http://example.test/base-1/replay",
                "diagnostics": {
                    "steps": 4,
                    "accepted_actions": 4,
                    "ticks_advanced": 0,
                    "work_progress": 0,
                    "utility_progress": 0,
                    "production_progress": 0,
                },
            },
            {
                "trial": 2,
                "model": "fake",
                "status": "completed",
                "score": 23.5,
                "work_score": 0.0,
                "completion_score": 0.0,
                "utility_score": 0.0,
                "production_score": 0.0,
                "work_progress": 0,
                "completion_progress": 0,
                "utility_progress": 0,
                "production_progress": 0,
                "public_run_url": "http://example.test/base-2",
                "public_replay_url": "http://example.test/base-2/replay",
                "diagnostics": {
                    "steps": 4,
                    "accepted_actions": 4,
                    "ticks_advanced": 0,
                    "work_progress": 0,
                    "utility_progress": 0,
                    "production_progress": 0,
                },
            },
    ]
    variant_runs = {
        "anthropic-keystroke": [
            {
                "trial": 1,
                "model": "anthropic-keystroke",
                "status": "completed",
                "score": 29.85,
                "work_score": 2.0,
                "completion_score": 0.0,
                "utility_score": 0.0,
                "production_score": 0.0,
                "work_progress": 5,
                "completion_progress": 0,
                "utility_progress": 0,
                "production_progress": 0,
                "public_run_url": "http://example.test/key-1",
                "public_replay_url": "http://example.test/key-1/replay",
                "diagnostics": {
                    "steps": 4,
                    "accepted_actions": 4,
                    "ticks_advanced": 508,
                    "work_progress": 5,
                    "utility_progress": 0,
                    "production_progress": 0,
                },
            },
            {
                "trial": 2,
                "model": "anthropic-keystroke",
                "status": "completed",
                "score": 23.5,
                "work_score": 0.0,
                "completion_score": 0.0,
                "utility_score": 0.0,
                "production_score": 0.0,
                "work_progress": 0,
                "completion_progress": 0,
                "utility_progress": 0,
                "production_progress": 0,
                "public_run_url": "http://example.test/key-2",
                "public_replay_url": "http://example.test/key-2/replay",
                "diagnostics": {
                    "steps": 4,
                    "accepted_actions": 4,
                    "ticks_advanced": 0,
                    "work_progress": 0,
                    "utility_progress": 0,
                    "production_progress": 0,
                },
            },
        ],
        "anthropic-dig-first": [
            {
                "trial": 1,
                "model": "anthropic-dig-first",
                "status": "completed",
                "score": 35.0,
                "work_score": 10.0,
                "completion_score": 10.0,
                "utility_score": 10.0,
                "production_score": 10.0,
                "complexity_score": 15.0,
                "work_progress": 25,
                "completion_progress": 25,
                "utility_progress": 5,
                "production_progress": 5,
                "complexity_progress": 38,
                "public_run_url": "http://example.test/dig-1",
                "public_replay_url": "http://example.test/dig-1/replay",
                "diagnostics": {
                    "steps": 4,
                    "accepted_actions": 4,
                    "ticks_advanced": 920,
                    "work_progress": 25,
                    "utility_progress": 5,
                    "utility_score": 10.0,
                    "production_progress": 5,
                    "production_score": 10.0,
                    "complexity_progress": 38,
                    "complexity_score": 15.0,
                },
            },
            {
                "trial": 2,
                "model": "anthropic-dig-first",
                "status": "completed",
                "score": 34.0,
                "work_score": 8.0,
                "completion_score": 8.0,
                "utility_score": 8.0,
                "production_score": 8.0,
                "complexity_score": 11.05,
                "work_progress": 20,
                "completion_progress": 20,
                "utility_progress": 4,
                "production_progress": 4,
                "complexity_progress": 28,
                "public_run_url": "http://example.test/dig-2",
                "public_replay_url": "http://example.test/dig-2/replay",
                "diagnostics": {
                    "steps": 4,
                    "accepted_actions": 4,
                    "ticks_advanced": 840,
                    "work_progress": 20,
                    "utility_progress": 4,
                    "utility_score": 8.0,
                    "production_progress": 4,
                    "production_score": 8.0,
                    "complexity_progress": 28,
                    "complexity_score": 11.05,
                },
            },
        ],
    }
    comparison = cli._build_suite_comparison(
        baseline_runs=baseline_runs,
        variant_runs=variant_runs,
    )
    progress_gate = cli._suite_progress_gate(comparison)
    report = {
        "ok": progress_gate["ok"],
        "suite_id": "live-agent-suite-test",
        "progress_gate": progress_gate,
        "comparison": comparison,
        "runs": {
            "baseline": baseline_runs,
            "variants": variant_runs,
        },
    }

    markdown_path, json_path = cli._write_live_agent_suite_artifacts(
        report=report,
        packet_path=None,
        server_artifacts_dir=str(tmp_path),
    )

    text = markdown_path.read_text(encoding="utf-8")
    json_text = json_path.read_text(encoding="utf-8")
    assert comparison["baseline"]["median_score"] == 23.5
    assert comparison["best_model"] == "anthropic-dig-first"
    assert comparison["best_median_delta"] == 11.0
    assert comparison["baseline"]["median_work_progress"] == 0.0
    assert comparison["variants"][1]["median_work_score"] == 9.0
    assert comparison["variants"][1]["median_work_progress"] == 22.5
    assert comparison["variants"][1]["median_completion_score"] == 9.0
    assert comparison["variants"][1]["median_completion_progress"] == 22.5
    assert comparison["variants"][1]["median_utility_score"] == 9.0
    assert comparison["variants"][1]["median_utility_progress"] == 4.5
    assert comparison["variants"][1]["median_production_score"] == 9.0
    assert comparison["variants"][1]["median_production_progress"] == 4.5
    assert comparison["variants"][1]["median_complexity_score"] == 13.03
    assert comparison["variants"][1]["median_complexity_progress"] == 33.0
    assert progress_gate["ok"] is True
    assert progress_gate["passing_models"] == ["anthropic-dig-first"]
    assert markdown_path == tmp_path / "live-agent-suite-test" / "live_agent_suite_report.md"
    assert json_path == tmp_path / "live-agent-suite-test" / "scorecard.json"
    assert "Best model: `anthropic-dig-first`" in text
    assert "Progress gate: PASS" in text
    assert "Passing progress models: `['anthropic-dig-first']`" in text
    assert "Median work progress: `22.5`" in text
    assert "Median completion progress: `22.5`" in text
    assert "Median utility progress: `4.5`" in text
    assert "Median production progress: `4.5`" in text
    assert "Median complexity progress: `33.0`" in text
    assert "http://example.test/dig-1" in text
    assert '"scorecard_json"' in json_text


def test_suite_progress_gate_requires_completion_utility_production_and_complexity():
    comparison = {
        "variants": [
            {
                "model": "anthropic-dig-first",
                "median_completion_progress": 25,
                "median_utility_progress": 5,
                "median_production_progress": 0,
                "median_complexity_progress": 38,
            }
        ]
    }

    gate = cli._suite_progress_gate(comparison)

    assert gate["ok"] is False
    assert gate["passing_models"] == []
    assert gate["models"] == [
        {
            "model": "anthropic-dig-first",
            "completion_progress": 25.0,
            "utility_progress": 5.0,
            "production_progress": 0.0,
            "complexity_progress": 38.0,
            "ok": False,
        }
    ]


def test_suite_progress_gate_requires_complexity_progress():
    comparison = {
        "variants": [
            {
                "model": "anthropic-dig-first",
                "median_completion_progress": 25,
                "median_utility_progress": 5,
                "median_production_progress": 5,
                "median_complexity_progress": 0,
            }
        ]
    }

    gate = cli._suite_progress_gate(comparison)

    assert gate["ok"] is False
    assert gate["passing_models"] == []
    assert gate["required"]["median_complexity_progress"] == "> 0"


def test_suite_ui_work_gate_requires_ui_progress_and_provenance():
    comparison = {
        "variants": [
            {
                "model": "anthropic-keystroke",
                "median_ui_work_progress": 8,
                "ui_score_provenance_runs": 1,
            },
            {
                "model": "anthropic-other",
                "median_ui_work_progress": 8,
                "ui_score_provenance_runs": 0,
            },
        ]
    }

    gate = cli._suite_ui_work_gate(comparison)

    assert gate["ok"] is True
    assert gate["passing_models"] == ["anthropic-keystroke"]
    assert gate["models"] == [
        {
            "model": "anthropic-keystroke",
            "ui_work_progress": 8.0,
            "ui_score_provenance_runs": 1,
            "ok": True,
        },
        {
            "model": "anthropic-other",
            "ui_work_progress": 8.0,
            "ui_score_provenance_runs": 0,
            "ok": False,
        },
    ]
    assert gate["required"]["score_provenance"] == "keystroke_ui_work_rect"

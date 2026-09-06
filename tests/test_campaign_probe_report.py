import json

import pytest

from scripts.campaign_probe_report import assess_probe, native_clock, report_probe


def experiment():
    return {
        "run_id": "probe",
        "model": "test/model",
        "status": "returned",
        "dispatches": 6,
        "usage": {"returned_responses": 3, "total_cost_usd": 0.003462525},
        "native_start": {"year": 30, "year_tick": 19309, "save_name": "campaign-resume"},
        "native_final": {"year": 30, "year_tick": 19309, "save_name": "campaign-resume"},
    }


def test_real_probe_failure_shape_does_not_become_success_or_dead_fortress():
    rows = [
        {
            "run_id": "probe",
            "step": 0,
            "observation": {"population": 7},
            "terminal_reason": {"code": "governed_review_contract_exhausted"},
        }
    ]
    result = assess_probe(experiment(), {"cleanup_verified": True}, rows)
    assert result["outcome"] == "model_action_contract_failure"
    assert result["action_rows"] == 0
    assert result["native_elapsed_ticks"] == 0
    assert result["trace_progress"]["elapsed_ticks"] is None
    assert result["last_observed_population"] == 7
    assert result["fortress_collapse"] == "not_assessed"
    assert result["dispatches_without_returned_usage"] == 3
    assert result["reported_model_cost_usd"] == 0.003462525
    assert result["billing_reconciled"] is False


@pytest.mark.parametrize(
    "code,outcome",
    [
        ("budget_cap_exceeded", "budget_limited_pause"),
        ("provider_invalid_response", "provider_failure"),
        ("new_unknown_error", "unclassified_failure"),
    ],
)
def test_failure_classes_are_not_gameplay_collapse(code, outcome):
    report = assess_probe(
        experiment(),
        {},
        [
            {"run_id": "probe", "terminal_reason": {"code": code}},
        ],
    )
    assert report["outcome"] == outcome
    assert report["fortress_collapse"] == "not_assessed"
    assert report["cleanup_verified"] is None


def test_returned_probe_is_not_year_two_acceptance():
    report = assess_probe(experiment(), {}, [{"run_id": "probe", "action": {"type": "WAIT"}}])
    assert report["outcome"] == "bounded_probe_returned"
    assert report["autonomous_year_two"] == "not_assessed"
    assert report["last_observed_population"] is None


def test_absent_or_cross_save_native_evidence_stays_unknown():
    data = experiment()
    data["native_final"]["save_name"] = "different"
    assert assess_probe(data, {}, [])["native_elapsed_ticks"] is None
    del data["native_final"]
    assert assess_probe(data, {}, [])["native_elapsed_ticks"] is None


@pytest.mark.parametrize("year,tick", [(True, 10), (30, False), (30, -1), (30, 403200)])
def test_invalid_native_time_is_not_coerced(year, tick):
    assert native_clock({"year": year, "year_tick": tick}) is None


def test_cross_run_trace_is_rejected():
    with pytest.raises(ValueError, match="identity"):
        assess_probe(experiment(), {}, [{"run_id": "another"}])


def test_report_is_source_bound_and_does_not_rewrite_artifacts(tmp_path):
    root = tmp_path / "probe"
    segment = root / "segments" / "probe"
    segment.mkdir(parents=True)
    (root / "experiment.json").write_text(json.dumps(experiment()))
    (root / "result.json").write_text('{"cleanup_verified": true}')
    (segment / "trace.jsonl").write_text('{"run_id": "probe", "step": 0}\n')
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    report = report_probe(root)
    assert len(report["source_sha256"]) == 3
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}

"""Version campaign measurements without changing historical benchmark readers."""

import hashlib
from pathlib import Path

import pytest

from fort_gym.bench import dfhack_backend
from fort_gym.bench.run import campaign_environment as module


@pytest.mark.parametrize(
    "name,digest",
    [
        ("fort_metrics.lua", "41b1c8f96a39fd9eab161b5fb27c635e9a6fae4e254a00576356473b9b4bb4b5"),
        ("job_metrics.lua", "1dfa6c28c5b369e4065b847af60e8dc032f8d5ae9fd8a4f35f55d56d455d72ff"),
    ],
)
def test_historical_metric_hooks_are_unchanged(name, digest):
    # Frozen main 6a699246: changing these bytes requires a benchmark protocol decision.
    source = Path(__file__).resolve().parents[1] / "hook" / name
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize(
    "campaign_reader,legacy_reader,campaign_name,legacy_name,timeout",
    [
        (
            module.read_campaign_fort_metrics,
            dfhack_backend.read_fort_metrics,
            "campaign_fort_metrics_v1.lua",
            "fort_metrics.lua",
            10.0,
        ),
        (
            module.read_campaign_job_metrics,
            dfhack_backend.read_job_metrics,
            "campaign_job_metrics_v1.lua",
            "job_metrics.lua",
            5.0,
        ),
    ],
)
def test_campaign_readers_use_versioned_hooks_without_plan_rectangles(
    monkeypatch, campaign_reader, legacy_reader, campaign_name, legacy_name, timeout
):
    calls = []

    def run(path, *args, **kwargs):
        calls.append((Path(path).name, args, kwargs))
        assert Path(path).is_file()
        return {"ok": True}

    monkeypatch.setattr(module, "run_lua_file", run)
    monkeypatch.setattr(dfhack_backend, "run_lua_file", run)
    assert campaign_reader() == {"ok": True}
    assert calls[-1] == (campaign_name, (), {"timeout": timeout})
    assert legacy_reader() == {"ok": True}
    assert calls[-1] == (legacy_name, (), {"timeout": timeout})


@pytest.mark.parametrize(
    "reader", [module.read_campaign_fort_metrics, module.read_campaign_job_metrics]
)
@pytest.mark.parametrize("error", [module.DFHackError("unreadable"), OSError("unreadable")])
def test_missing_campaign_measurements_are_not_fabricated(monkeypatch, reader, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(module, "run_lua_file", fail)
    assert reader() == {"ok": False, "error": "unreadable"}

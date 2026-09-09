from types import SimpleNamespace

import pytest

from fort_gym.bench import dfhack_exec
from fort_gym.bench.run import campaign_environment
from scripts import campaign_rpc_probe as probe


@pytest.mark.parametrize("wrong_clock", [False, True])
def test_probe_only_observes_and_closes_environment(tmp_path, monkeypatch, wrong_clock):
    calls = []

    def observe():
        calls.append("observe")
        return {
            "year": 30, "year_tick": 223384 if wrong_clock else 223383,
            "pause_state": True, "population": 12, "stocks": {"drink": 404},
            "private_food_measurement": {"available": False, "error_type": "fixture"},
        }

    monkeypatch.setattr(campaign_environment, "NativeCampaignEnvironment", lambda **kw: SimpleNamespace(
        observe=observe, screen_capture=lambda: {"width": 120, "height": 40, "tiles": []},
        close=lambda: calls.append("close"),
    ))
    monkeypatch.setattr(probe, "capture_resources", lambda: {"fixture": True})
    monkeypatch.setattr(dfhack_exec, "run_dfhack", lambda *a, **k: None)
    args = SimpleNamespace(runtime=tmp_path, output=tmp_path / "receipt.json")
    if wrong_clock:
        with pytest.raises(AssertionError):
            probe.worker(args)
        assert not args.output.exists()
    else:
        result = probe.worker(args)
        assert len(result["observations"]) == 16
        assert result["model_calls"] == result["gameplay_actions"] == 0
        assert result["calendar_unchanged"] and result["screen_unchanged"]
    assert calls[-1] == "close"
    with pytest.raises(AssertionError, match="CLI fallback"):
        dfhack_exec.run_dfhack([])

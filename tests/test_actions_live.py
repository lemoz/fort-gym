from __future__ import annotations

import os
import pytest

LIVE = os.environ.get("DFHACK_LIVE") == "1"


@pytest.mark.skipif(not LIVE, reason="requires live DFHack")
def test_order_bed_ok():
    from fort_gym.bench.dfhack_backend import queue_manager_order

    result = queue_manager_order("bed", 1)
    assert result.get("ok") is True


@pytest.mark.skipif(not LIVE, reason="requires live DFHack")
def test_order_invalid_item():
    from fort_gym.bench.dfhack_backend import queue_manager_order

    result = queue_manager_order("sword_of_gods", 1)
    assert result.get("ok") is False


@pytest.mark.skipif(not LIVE, reason="requires live DFHack")
def test_designate_rect_clamp():
    from fort_gym.bench.dfhack_backend import designate_rect

    result = designate_rect("dig", 0, 0, 0, 200, 200, 0)
    assert result.get("ok") is False
    assert result.get("error") == "rect_too_large"


def test_read_work_metrics_rejects_oversized_rect_without_live_dfhack():
    from fort_gym.bench.dfhack_backend import read_work_metrics

    result = read_work_metrics((0, 0, 0, 200, 200, 0))
    assert result.get("ok") is False
    assert result.get("error") == "rect_too_large"


def test_read_work_metrics_rejects_z_spans_without_live_dfhack():
    from fort_gym.bench.dfhack_backend import read_work_metrics

    result = read_work_metrics((0, 0, 0, 1, 1, 1))
    assert result.get("ok") is False
    assert result.get("error") == "z_span_not_supported"


def test_read_map_snapshot_rejects_oversized_rect_without_live_dfhack():
    from fort_gym.bench.dfhack_backend import read_map_snapshot

    result = read_map_snapshot((0, 0, 0, 200, 200, 0))
    assert result.get("ok") is False
    assert result.get("error") == "rect_too_large"


def test_read_map_snapshot_rejects_z_spans_without_live_dfhack():
    from fort_gym.bench.dfhack_backend import read_map_snapshot

    result = read_map_snapshot((0, 0, 0, 1, 1, 1))
    assert result.get("ok") is False
    assert result.get("error") == "z_span_not_supported"


def test_complete_dig_rect_rejects_oversized_rect_without_live_dfhack():
    from fort_gym.bench.dfhack_backend import complete_dig_rect

    result = complete_dig_rect(0, 0, 0, 200, 200, 0)
    assert result.get("ok") is False
    assert result.get("error") == "rect_too_large"


def test_complete_dig_rect_rejects_z_spans_without_live_dfhack():
    from fort_gym.bench.dfhack_backend import complete_dig_rect

    result = complete_dig_rect(0, 0, 0, 1, 1, 1)
    assert result.get("ok") is False
    assert result.get("error") == "z_span_not_supported"


def test_build_workshop_rejects_invalid_kind_without_live_dfhack():
    from fort_gym.bench.dfhack_backend import build_workshop

    result = build_workshop("MagmaForge", 51, 36, 0)
    assert result.get("ok") is False
    assert result.get("error") == "invalid_kind"


def test_build_workshop_rejects_outside_target_room_without_live_dfhack():
    from fort_gym.bench.dfhack_backend import build_workshop

    result = build_workshop("CarpenterWorkshop", 0, 0, 0)
    assert result.get("ok") is False
    assert result.get("error") == "outside_work_rect"


def test_build_workshop_allows_planned_annex_without_live_dfhack(monkeypatch):
    from fort_gym.bench import dfhack_backend

    calls = []

    def fake_run_lua_file(path, *args):
        calls.append((path, args))
        return {"ok": True, "kind": args[0], "x": int(args[1]), "y": int(args[2]), "z": int(args[3])}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run_lua_file)

    result = dfhack_backend.build_workshop("CarpenterWorkshop", 59, 36, 0)

    assert result == {"ok": True, "kind": "CarpenterWorkshop", "x": 59, "y": 36, "z": 0}
    assert calls

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

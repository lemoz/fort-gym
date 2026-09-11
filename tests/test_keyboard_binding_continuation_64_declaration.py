"""Decision-64 continuation declaration, not gameplay proof."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_exact_saved_origin_and_unchanged_condition():
    folder = ROOT / "experiments/keyboard_binding_continuation_20260911"
    prior_window = json.loads((folder / "window-32-64.json").read_text())
    window = json.loads((folder / "window-64-96.json").read_text())
    prior = json.loads(
        (
            ROOT / "experiments/evidence/keyboard_binding_astra_r1_continuation_32_64_20260911.json"
        ).read_text()
    )
    assert window["continuation_checkpoint_sha256"] == prior["checkpoint_sha256"]
    assert window["continuation_from_next_step"] == prior["responses"] == 64
    assert window["steps_per_segment"] == 32 and window["max_segments"] == 1
    for name in ("continuation_checkpoint_sha256", "continuation_from_next_step"):
        window.pop(name)
        prior_window.pop(name)
    assert window == prior_window

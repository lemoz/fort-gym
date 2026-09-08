"""Public restarted branch retains its original failure and full loss accounting."""
import json

import pytest

from fort_gym.bench.api import campaign_keyboard_records as records
from tests.test_campaign_keyboard_records import evidence_root  # noqa: F401


def test_presave_restart_is_saved_but_adds_no_elapsed_time(evidence_root):  # noqa: F811
    path = evidence_root / "experiments/evidence" / records.PRESAVE_RESTARTS[0]
    source = json.loads(path.read_text())
    source["private_prompt"] = "private-sentinel"
    source["progress"]["screen"] = "private-sentinel"
    path.write_text(json.dumps(source))
    data = records.keyboard_campaign_records(evidence_root)
    row = data["restarts"][-1]
    assert row["progress"]["checkpoint_cursor"] == 647
    assert row["progress"]["new_elapsed_ticks"] == 0
    assert row["progress"]["retained_elapsed_ticks"] == 143400
    assert row["progress"]["cumulative_model_responses"] == 727
    assert row["progress"]["discarded_native_ticks"] == 23200
    assert row["native_save_loss_restarts"] == 2
    assert row["usage"]["campaign_tokens"] == 23330797
    assert row["usage"]["all_attempt_tokens"] == 23399801
    assert row["usage"]["lost_tail_tokens_retained"] == 1968854
    assert row["usage"]["reported_charge_usd"] is None
    assert row["final_checkpoint_fresh_reload_verified"] is False
    assert data["presave_failures"][-1]["status"] == "failed"
    assert data["continuation_events"][-1] == {"kind": "restart", "id": row["restart_id"]}
    assert "private-sentinel" not in json.dumps(data)


@pytest.mark.parametrize("section,field,value", [
    (None, "snapshot_profile", "native_menu_preserving_save/v3"),
    (None, "source_save_attempt_sha256", "bad"),
    (None, "independent_audit_sha256", False),
    (None, "save_failure_stage", "after_save"),
    (None, "native_save_loss_restarts", 1),
    (None, "native_save_loss_restarts", True),
    (None, "steps_per_segment", 64),
    (None, "steps_per_segment", True),
    (None, "final_checkpoint_fresh_reload_verified", True),
    (None, "captured_screen_size", [80, 25]),
    (None, "original_failure", "unknown"),
    (None, "parent_checkpoint_sha256", "a" * 64),
    ("progress", "discarded_native_ticks", 21200),
    ("progress", "new_elapsed_ticks", 21200),
    ("progress", "cumulative_model_responses", 663),
    ("progress", "checkpoint_cursor", 711),
    ("usage", "lost_tail_tokens_retained", 0),
    ("usage", "campaign_tokens", 21361943),
    ("usage", "reported_charge_usd", 0),
])
def test_presave_restart_cannot_erase_old_loss_or_restore_unsaved_ticks(
    evidence_root, section, field, value  # noqa: F811
):
    path = evidence_root / "experiments/evidence" / records.PRESAVE_RESTARTS[0]
    source = json.loads(path.read_text())
    (source[section] if section else source)[field] = value
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError):
        records.keyboard_campaign_records(evidence_root)

"""A pre-save assertion permits declared loss, never automatic replay or recovery."""

import hashlib
import json

import pytest

from fort_gym.bench.agent.keyboard_exchange import read
from fort_gym.bench.run.keyboard_restart import validate_discontinuities
from tests.test_keyboard_restart import failed as failed, prepare
from tests.test_keyboard_runtime import saved as saved


def retain_presave_evidence(failed, assertion="Identity probe requires a native screen"):
    _, source, _ = failed
    segment = source / "segment-0"
    result_path = segment / "result.json"
    result = read(result_path)
    result["checkpoint_error"] = "Native menu identity probe returned malformed JSON"
    result["private_save_attempt_retained"] = True
    result_path.write_text(json.dumps(result))
    world, screen = read(segment / "native-after.json"), read(segment / "final-screen.json")
    attempt = {
        "schema_version": "fortgym.native-menu-save-attempt/v1",
        "identity_before_raw": f"(lua command):22: {assertion}\n"
        "stack traceback:\n\t[C]: in function 'assert'",
        "screen_before": screen,
        "screen_after": screen,
        "world_before": world,
        "world_after": world,
    }
    path = segment / "save-attempt.json"
    path.write_text(json.dumps(attempt))
    return path


@pytest.mark.parametrize("assertion", [
    "Identity probe requires a native screen", "Snapshot cannot hide a dismissed screen",
])
def test_presave_restart_binds_original_attempt_and_preserves_usage(failed, assertion):
    path = retain_presave_evidence(failed, assertion)
    record = prepare(failed)
    assert record["save_failure_stage"] == "identity_before_save"
    assert record["source_save_attempt_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert record["lost_elapsed_ticks"] == 20
    assert record["retained_usage"]["returned_responses"] == 3


@pytest.mark.parametrize("assertion", [
    "Identity probe requires a native screen", "Snapshot cannot hide a dismissed screen",
])
@pytest.mark.parametrize("mutation", [
    "missing", "symlink", "schema", "raw_json", "wrong_assertion", "postsave_assertion",
    "save_operation_raw", "save_operation", "identity_before", "identity_after_raw",
    "identity_after", "copied_native_save", "capture_errors", "screen_changed",
    "world_changed", "empty_world", "empty_screen", "wrong_final_world",
    "wrong_final_screen", "not_retained", "unknown_error", "new_native_save",
])
def test_presave_restart_refuses_incomplete_or_postsave_evidence(failed, mutation, assertion):
    path = retain_presave_evidence(failed, assertion)
    attempt = read(path)
    if mutation == "missing":
        path.unlink()
    elif mutation == "symlink":
        actual = path.with_suffix(".original.json")
        path.rename(actual)
        path.symlink_to(actual)
    elif mutation in {"not_retained", "unknown_error"}:
        result_path = path.parent / "result.json"
        result = read(result_path)
        result["private_save_attempt_retained" if mutation == "not_retained" else "checkpoint_error"] = False
        result_path.write_text(json.dumps(result))
    elif mutation == "new_native_save":
        (failed[1] / "runtime-0/runtime/data/save/fixture/world.sav").write_text("newer save")
    else:
        if mutation == "schema":
            attempt["schema_version"] = "unknown"
        elif mutation == "raw_json":
            attempt["identity_before_raw"] = "{}"
        elif mutation == "wrong_assertion":
            attempt["identity_before_raw"] = "(lua command):22: Unrelated error\nstack traceback:\n"
        elif mutation == "postsave_assertion":
            attempt["identity_after_raw"] = attempt.pop("identity_before_raw")
        elif mutation in {"screen_changed", "world_changed"}:
            attempt[mutation.split("_")[0] + "_after"]["changed"] = True
        elif mutation in {"empty_world", "empty_screen"}:
            for suffix in ("before", "after"):
                attempt[mutation.split("_")[1] + "_" + suffix] = {}
        elif mutation in {"wrong_final_world", "wrong_final_screen"}:
            kind = mutation.split("_")[-1]
            for suffix in ("before", "after"):
                attempt[kind + "_" + suffix]["changed"] = True
        else:
            attempt[mutation] = {}
        path.write_text(json.dumps(attempt))
    with pytest.raises(ValueError):
        prepare(failed)


@pytest.mark.parametrize("field,value", [
    ("save_failure_stage", "identity_after_save"),
    ("save_failure_stage", None),
    ("source_save_attempt_sha256", "bad"),
    ("source_save_attempt_sha256", None),
])
def test_presave_discontinuity_requires_stage_and_digest(failed, field, value):
    retain_presave_evidence(failed)
    record = prepare(failed)
    if value is None:
        del record[field]
    else:
        record[field] = value
    with pytest.raises(ValueError, match="failure-stage"):
        validate_discontinuities([record])

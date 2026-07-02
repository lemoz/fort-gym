from __future__ import annotations

from pathlib import Path

from fort_gym.bench import dfhack_backend
from fort_gym.bench import dfhack_exec


def test_run_lua_file_parses_last_json_line(monkeypatch) -> None:
    monkeypatch.setattr(
        dfhack_exec,
        "run_dfhack",
        lambda *args, **kwargs: "notice from dfhack\n\x1b[0m{\"ok\": true, \"value\": 3}\x1b[0m",
    )

    assert dfhack_exec.run_lua_file("/tmp/hook.lua") == {"ok": True, "value": 3}


def test_hook_path_prefers_repo_hook_over_installed_copy(tmp_path, monkeypatch) -> None:
    repo_hook = tmp_path / "repo" / "hook"
    installed_hook = tmp_path / "installed" / "hook"
    repo_hook.mkdir(parents=True)
    installed_hook.mkdir(parents=True)
    (repo_hook / "work_metrics.lua").write_text("-- repo", encoding="utf-8")
    (installed_hook / "work_metrics.lua").write_text("-- stale installed", encoding="utf-8")
    monkeypatch.setattr(dfhack_backend, "REPO_HOOK_ROOT", repo_hook)
    monkeypatch.setattr(dfhack_backend, "HOOK_ROOT", installed_hook)

    assert Path(dfhack_backend._hook_path("work_metrics.lua")) == repo_hook / "work_metrics.lua"


def test_prepare_keystroke_workshop_target_moves_cursor_before_confirm() -> None:
    hook_path = (
        Path(__file__).resolve().parents[1]
        / "hook"
        / "prepare_keystroke_target.lua"
    )
    hook_text = hook_path.read_text(encoding="utf-8")

    assert "local function append_cursor_moves" in hook_text
    assert "placement_cursor_before_moves" in hook_text
    assert "blocked_workshop_targets" in hook_text
    assert "blocked_workshop_targets[workshop_target_key(x1, y1, z)]" in hook_text
    assert (
        "append_cursor_moves(recommended_keys, placement_cursor_x, placement_cursor_y, x1, y1)"
        in hook_text
    )
    assert "'HOTKEY_BUILDING_WORKSHOP_CARPENTER',\n  }\n  append_cursor_moves" in hook_text


def test_prepare_keystroke_target_passes_blocked_workshop_targets(monkeypatch) -> None:
    captured = {}

    def fake_run_lua_file(path, *args, **kwargs):
        captured["path"] = path
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run_lua_file)

    assert dfhack_backend.prepare_keystroke_target(
        "workshop",
        blocked_workshop_targets=[(97, 93, 177), (88, 98, 177)],
    ) == {"ok": True}

    assert captured["args"] == ("workshop", "97,93,177;88,98,177")
    assert captured["kwargs"]["timeout"] == 10.0


def test_view_state_helpers_use_dedicated_hooks(monkeypatch) -> None:
    calls = []

    def fake_run_lua_file(path, *args, **kwargs):
        calls.append((Path(path).name, args, kwargs))
        return {"ok": True, "window_x": 12}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run_lua_file)

    assert dfhack_backend.read_view_state()["ok"] is True
    assert dfhack_backend.restore_view_state(
        {
            "ok": True,
            "window_x": 12,
            "window_y": 34,
            "window_z": 5,
            "cursor_x": -30000,
            "cursor_y": -30000,
            "cursor_z": -30000,
        }
    )["ok"] is True

    assert calls[0][0] == "view_state.lua"
    assert calls[1][0] == "restore_view_state.lua"
    assert calls[1][1] == ("12", "34", "5", "-30000", "-30000", "-30000")


def test_fortress_workshop_rect_expands_short_live_targets_for_workshop_footprint() -> None:
    assert dfhack_backend._fortress_workshop_rect((94, 91, 177, 97, 92, 177)) == (
        101,
        91,
        177,
        105,
        95,
        177,
    )


def test_build_workshop_allows_observed_extra_build_site(monkeypatch) -> None:
    captured = {}

    def fake_run_lua_file(path, *args, **kwargs):
        captured["args"] = args
        return {"ok": True}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run_lua_file)

    result = dfhack_backend.build_workshop(
        "CarpenterWorkshop",
        88,
        96,
        177,
        work_rect=(94, 91, 177, 97, 92, 177),
        extra_allowed_rects=[(88, 96, 177, 90, 98, 177)],
    )

    assert result == {"ok": True}
    assert captured["args"] == ("CarpenterWorkshop", "88", "96", "177")


def test_build_workshop_hook_uses_existing_material_item() -> None:
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "build_workshop.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    assert "find_nearest_building_material" in hook_text
    assert "items = { material_item }" in hook_text
    assert "no_building_material" in hook_text


def test_order_make_hook_prefers_direct_workshop_jobs() -> None:
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "order_make.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    assert "require('dfhack.workshops')" in hook_text
    assert "mode = 'workshop_job'" in hook_text
    assert "dfhack.job.linkIntoWorld(job, true)" in hook_text
    assert "manager_recorded = manager_recorded" in hook_text
    assert "manager_orders:insert('#', wo)" in hook_text


def test_designate_rect_reports_designation_counts() -> None:
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "designate_rect.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    assert "newly_designated" in hook_text
    assert "already_designated" in hook_text
    assert "non_wall_tiles" in hook_text
    assert "missing_tiles" in hook_text
    assert "autochop" in hook_text


def test_prepare_keystroke_tree_material_target_uses_broad_selection() -> None:
    hook_path = (
        Path(__file__).resolve().parents[1]
        / "hook"
        / "prepare_keystroke_target.lua"
    )
    hook_text = hook_path.read_text(encoding="utf-8")

    assert "local TREE_SELECT_WIDTH = 7" in hook_text
    assert "local TREE_SELECT_HEIGHT = 3" in hook_text
    assert "count_designatable_rect" in hook_text
    assert "selection_payload(" in hook_text
    assert "chop a broad visible tree area" in hook_text


def test_job_metrics_is_read_only_and_reports_crew() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "hook" / "job_metrics.lua"
    ).read_text(encoding="utf-8")
    for needle in (
        "mining_labor",
        "carpentry_labor",
        "woodcutting_labor",
        "construct_building",
        "getBuildStage",
        "shrub_or_other",
        "has_worker",
    ):
        assert needle in script
    # read-only: must never write designations or tiletypes
    assert "designation[dx][dy].dig ~=" in script
    assert "= df.tile_dig_designation.Default" not in script
    assert "block.tiletype[dx][dy] =" not in script
    assert "flags.designated = true" not in script

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


def test_build_workshop_passes_site_through_to_locality_hook(monkeypatch) -> None:
    captured = {}

    def fake_run_lua_file(path, *args, **kwargs):
        captured["args"] = args
        return {"ok": True}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run_lua_file)

    result = dfhack_backend.build_workshop("CarpenterWorkshop", 88, 96, 177)

    assert result == {"ok": True}
    assert captured["args"] == ("CarpenterWorkshop", "88", "96", "177")


def test_placement_hooks_enforce_fort_locality() -> None:
    for hook_name in ("build_workshop.lua", "place_furniture.lua"):
        hook_path = Path(__file__).resolve().parents[1] / "hook" / hook_name
        hook_text = hook_path.read_text(encoding="utf-8")
        assert "MAX_LOCALITY = 24" in hook_text
        assert "too_far_from_fort" in hook_text
        assert "collect_locality_anchors" in hook_text


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


def test_designate_rect_chop_is_bounded_tree_designation() -> None:
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "designate_rect.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    # chop designates tree trunks inside the rect, like a player's d-t
    assert "trees_designated" in hook_text
    assert "non_tree_tiles" in hook_text
    assert "df.tiletype_material.TREE" in hook_text
    # the old global autochop pulse (broken on this DFHack: no such script) is gone
    assert "autochop" not in hook_text


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


def test_job_metrics_reports_finished_goods_counts() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "hook" / "job_metrics.lua"
    ).read_text(encoding="utf-8")
    for needle in ("GOODS_ITEM_TYPES", "'BED'", "'BARREL'", "'WOOD'", "out.goods"):
        assert needle in script


def test_place_furniture_hook_installs_existing_items_only() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "hook" / "place_furniture.lua"
    ).read_text(encoding="utf-8")
    for needle in (
        "df.item_type.BED",
        "df.building_type.Bed",
        "no_finished_item_available",
        "constructBuilding",
        "jobs_count",
    ):
        assert needle in script
    # legality: never creates items, only installs existing produced ones
    assert "createItem" not in script


def test_job_metrics_reports_placed_furniture() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "hook" / "job_metrics.lua"
    ).read_text(encoding="utf-8")
    assert "placed_furniture" in script
    assert "df.building_type.Bed" in script


def test_build_construction_hook_enforces_locality_and_uses_existing_material() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "hook" / "build_construction.lua"
    ).read_text(encoding="utf-8")
    for needle in (
        "too_far_from_fort",
        "df.construction_type.Wall",
        "no_building_material",
        "constructBuilding",
    ):
        assert needle in script
    # legality: never creates items, only uses existing material items
    assert "createItem" not in script


def test_build_construction_reports_occupied_and_wall_tiles() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "hook" / "build_construction.lua"
    ).read_text(encoding="utf-8")
    assert "tile_occupied_by_building" in script
    assert "already_wall" in script


def test_job_metrics_reports_furniture_positions() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "hook" / "job_metrics.lua"
    ).read_text(encoding="utf-8")
    assert "placed_furniture_positions" in script


def test_fort_metrics_renders_minimap_grid() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "hook" / "fort_metrics.lua"
    ).read_text(encoding="utf-8")
    for needle in ("map_rows", "map_origin", "BUILDING_CHARS", "construction_set"):
        assert needle in script


def test_fort_metrics_anchors_on_citizens_and_marks_dwarves() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "hook" / "fort_metrics.lua"
    ).read_text(encoding="utf-8")
    assert "citizen_positions" in script
    assert "citizen_lookup" in script
    assert "'@'" in script


def test_fort_metrics_marks_queued_constructions_without_sealing_rooms() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "hook" / "fort_metrics.lua"
    ).read_text(encoding="utf-8")
    # queued (unbuilt) constructions render as 'x' on the minimap...
    assert "pending_construction_tiles" in script
    assert "ch = 'x'" in script
    assert "pending_constructions = pending_constructions" in script
    # ...but must never enter the enclosure flood-fill boundary set: the
    # detector's construction_set reads world.constructions (built only).
    boundary_block = script[script.index("local construction_set"):]
    boundary_block = boundary_block[: boundary_block.index("BUILDING_CHARS")]
    assert "pending" not in boundary_block

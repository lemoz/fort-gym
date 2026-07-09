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
    for hook_name in ("build_workshop.lua", "place_furniture.lua", "build_farm_plot.lua"):
        hook_path = Path(__file__).resolve().parents[1] / "hook" / hook_name
        hook_text = hook_path.read_text(encoding="utf-8")
        assert "MAX_LOCALITY = 24" in hook_text
        assert "too_far_from_fort" in hook_text
        assert "collect_locality_anchors" in hook_text


def test_place_furniture_hook_reports_tile_state_on_failure() -> None:
    hook_text = (
        Path(__file__).resolve().parents[1] / "hook" / "place_furniture.lua"
    ).read_text(encoding="utf-8")
    # run 0a1be1c5 burned 40 actions on bare construct_failed: the tile is
    # classified before placement so the rejection names the visible cause
    for needle in (
        "tile_occupied_by_building",
        "tile_not_open_floor",
        "tile_hidden_unexplored",
        "tile_placement_error",
    ):
        assert needle in hook_text


def test_build_workshop_hook_uses_existing_material_item() -> None:
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "build_workshop.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    assert "find_nearest_building_material" in hook_text
    assert "items = { material_item }" in hook_text
    assert "no_building_material" in hook_text


def test_build_workshop_hook_supports_still_subtype() -> None:
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "build_workshop.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    # Still extends the same bounded workshop placement as CarpenterWorkshop
    assert "Still = df.workshop_type.Still" in hook_text
    assert "CarpenterWorkshop = df.workshop_type.Carpenters" in hook_text
    assert "local subtype = SUBTYPES[kind]" in hook_text
    # generalized before/after counts work for any kind, not just carpenter
    assert "before_workshops_of_kind" in hook_text
    assert "after_workshops_of_kind" in hook_text
    # backward-compatible carpenter-specific fields are still emitted
    assert "before_carpenter_workshops" in hook_text
    assert "after_carpenter_workshops" in hook_text


def test_build_workshop_passes_still_kind_through_to_backend(monkeypatch) -> None:
    captured = {}

    def fake_run_lua_file(path, *args, **kwargs):
        captured["args"] = args
        return {"ok": True, "kind": "Still"}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run_lua_file)

    result = dfhack_backend.build_workshop("Still", 88, 96, 177)

    assert result == {"ok": True, "kind": "Still"}
    assert captured["args"] == ("Still", "88", "96", "177")


def test_build_workshop_allowed_workshops_include_still() -> None:
    # Still must be routed through ALLOWED_WORKSHOPS same as CarpenterWorkshop
    assert "Still" in dfhack_backend.ALLOWED_WORKSHOPS
    assert "CarpenterWorkshop" in dfhack_backend.ALLOWED_WORKSHOPS

def test_build_farm_plot_hook_is_bounded_and_reports_counts() -> None:
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "build_farm_plot.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    assert "rect_too_large" in hook_text
    assert "df.building_type.FarmPlot" in hook_text
    assert "before_farm_plots" in hook_text
    assert "after_farm_plots" in hook_text
    # obvious per-tile placement problems reuse place_furniture's checks
    assert "tile_occupied_by_building" in hook_text
    assert "tile_hidden_unexplored" in hook_text
    assert "tile_not_open_floor" in hook_text
    assert "tile_placement_error" in hook_text


def test_build_farm_plot_hook_checks_locality_at_all_four_corners() -> None:
    # A single-corner near_fort check can pass while the opposite corner of
    # an up-to-5x5 footprint sits past the 24-tile locality bound. Unlike
    # build_workshop.lua/place_furniture.lua (single-tile placements, where
    # one check is correct), build_farm_plot.lua's footprint is a rect, so
    # it must check all four corners like build_construction.lua's per-tile
    # near_fort loop.
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "build_farm_plot.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    assert "{ rx1, ry1 }" in hook_text
    assert "{ rx1, ry2 }" in hook_text
    assert "{ rx2, ry1 }" in hook_text
    assert "{ rx2, ry2 }" in hook_text
    assert "for _, corner in ipairs(corners) do" in hook_text


def test_build_farm_plot_hook_requires_no_material_item() -> None:
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "build_farm_plot.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    # farm plots consume no material item, unlike build_workshop.lua's
    # items = { material_item } -- the constructBuilding call omits `items`
    assert "consumes no material item" in hook_text
    assert "items = { material_item }" not in hook_text
    assert "find_nearest_building_material" not in hook_text


def test_build_farm_plot_wraps_bounded_lua_hook(monkeypatch) -> None:
    captured: dict = {}

    def fake_run_lua_file(path, *args, **kwargs):
        captured["path"] = path
        captured["args"] = args
        return {"ok": True, "kind": "FarmPlot", "before_farm_plots": 0, "after_farm_plots": 1}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run_lua_file)

    result = dfhack_backend.build_farm_plot(90, 95, 177, 92, 97)

    assert result == {
        "ok": True,
        "kind": "FarmPlot",
        "before_farm_plots": 0,
        "after_farm_plots": 1,
    }
    assert captured["args"] == ("90", "95", "177", "92", "97")
    assert Path(captured["path"]).name == "build_farm_plot.lua"


def test_build_farm_plot_defaults_x2_y2_to_single_tile(monkeypatch) -> None:
    captured: dict = {}

    def fake_run_lua_file(path, *args, **kwargs):
        captured["args"] = args
        return {"ok": True}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run_lua_file)

    dfhack_backend.build_farm_plot(90, 95, 177)

    assert captured["args"] == ("90", "95", "177", "90", "95")


def test_build_farm_plot_rejects_oversized_rect() -> None:
    result = dfhack_backend.build_farm_plot(0, 0, 0, 6, 0)

    assert result == {"ok": False, "error": "rect_too_large"}


def test_order_make_hook_prefers_direct_workshop_jobs() -> None:
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "order_make.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    assert "require('dfhack.workshops')" in hook_text
    assert "mode = 'workshop_job'" in hook_text
    assert "dfhack.job.linkIntoWorld(job, true)" in hook_text
    assert "manager_recorded = manager_recorded" in hook_text
    assert "manager_orders:insert('#', wo)" in hook_text


def test_order_make_hook_supports_brew_item_at_still() -> None:
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "order_make.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    # live validation 2026-07-08: df.job_type.BrewDrink does not exist on
    # 0.47.05 -- brewing is the BREW_DRINK_FROM_PLANT CustomReaction
    assert (
        "brew = { job = 'CustomReaction', "
        "reaction = 'BREW_DRINK_FROM_PLANT', workshop = 'Still' }" in hook_text
    )
    assert "job_definition_for(workshop, job_type, spec.reaction)" in hook_text
    assert "first_workshop_of_subtype(spec.workshop)" in hook_text
    # existing carpenter-scoped items still route to Carpenters
    assert "bed = { job = 'ConstructBed', workshop = 'Carpenters' }" in hook_text


def test_order_make_brew_item_is_allowlisted() -> None:
    assert "brew" in dfhack_backend.ALLOWED_ITEMS
    assert dfhack_backend.ALLOWED_ITEMS >= {
        "bed",
        "door",
        "table",
        "chair",
        "barrel",
        "bin",
        "brew",
    }


def test_designate_rect_reports_designation_counts() -> None:
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "designate_rect.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    assert "newly_designated" in hook_text
    assert "already_designated" in hook_text
    assert "non_wall_tiles" in hook_text
    assert "missing_tiles" in hook_text


def test_designate_rect_dig_channel_never_writes_non_wall_tiles() -> None:
    # dig/channel must only ever write a real designation onto WALL tiles.
    # Writing it unconditionally on a non-wall tile (e.g. a SHRUB) would
    # silently create a real Gather-Plants designation the harness never
    # reports and the agent was never told would happen.
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "designate_rect.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    assert "if status ~= 'non_wall_tiles' then" in hook_text


def test_designate_rect_chop_is_bounded_tree_designation() -> None:
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "designate_rect.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    # chop designates tree trunks inside the rect, like a player's d-t
    assert "trees_designated" in hook_text
    assert "non_tree_tiles" in hook_text
    assert "df.tiletype_material.TREE" in hook_text
    # the old global autochop pulse (broken on this DFHack: no such script) is gone
    assert "autochop" not in hook_text


def test_designate_rect_gather_is_bounded_shrub_designation() -> None:
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "designate_rect.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    # gather designates shrub tiles inside the rect, like a player's d-p
    assert "gather = true" in hook_text
    assert "df.tiletype_shape.SHRUB" in hook_text
    assert "shrubs_designated" in hook_text
    assert "already_designated" in hook_text
    assert "non_shrub_tiles" in hook_text
    # shares the bounded rect (30x30, one z-level) with dig/channel/chop
    assert "rect_too_large" in hook_text
    assert "bad_rect" in hook_text


def test_designate_rect_gather_wraps_bounded_lua_hook(monkeypatch) -> None:
    captured: dict = {}

    def fake_run_lua_file(path, *args, **kwargs):
        captured["path"] = path
        captured["args"] = args
        return {"ok": True, "kind": "gather", "shrubs_designated": 4}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run_lua_file)

    result = dfhack_backend.designate_rect("gather", 50, 35, 0, 52, 37, 0)

    assert result == {"ok": True, "kind": "gather", "shrubs_designated": 4}
    assert captured["args"] == ("gather", "50", "35", "0", "52", "37", "0")
    assert Path(captured["path"]).name == "designate_rect.lua"


def test_unsuspend_jobs_hook_is_bounded_and_reports_counts() -> None:
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "unsuspend_jobs.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    # bounded rect: rejects bad/missing coords and mismatched z-levels
    assert "bad_rect" in hook_text
    assert "rect_too_large" in hook_text
    # walks the live jobs list (same pattern as job_metrics.lua)
    assert "df.global.world.jobs.list.next" in hook_text
    assert "job.flags.suspend" in hook_text
    # reports honest counts, ok=true even when nothing was unsuspended
    assert "unsuspended" in hook_text
    assert "suspended_found" in hook_text
    assert "ok = true" in hook_text


def test_unsuspend_jobs_hook_only_flips_suspend_flag() -> None:
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "unsuspend_jobs.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    # mirrors the player's q-menu unsuspend: never completes the job itself,
    # never mutates tile designations or building/block flags
    assert "does NOT complete any work" in hook_text
    assert "job.flags.suspend = false" in hook_text
    assert "designation.dig =" not in hook_text
    assert "block.flags.designated" not in hook_text


def test_unsuspend_jobs_wraps_bounded_lua_hook(monkeypatch) -> None:
    captured: dict = {}

    def fake_run_lua_file(path, *args, **kwargs):
        captured["path"] = path
        captured["args"] = args
        return {"ok": True, "unsuspended": 1, "suspended_found": 1}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run_lua_file)

    result = dfhack_backend.unsuspend_jobs(98, 95, 177, 102, 99, 177)

    assert result == {"ok": True, "unsuspended": 1, "suspended_found": 1}
    assert captured["args"] == ("98", "95", "177", "102", "99", "177")
    assert Path(captured["path"]).name == "unsuspend_jobs.lua"


def test_unsuspend_jobs_rejects_oversized_rect() -> None:
    result = dfhack_backend.unsuspend_jobs(0, 0, 0, 11, 0, 0)

    assert result == {"ok": False, "error": "rect_too_large"}


def test_unsuspend_jobs_rejects_multi_z_rect() -> None:
    result = dfhack_backend.unsuspend_jobs(0, 0, 0, 2, 2, 1)

    assert result == {"ok": False, "error": "z_span_not_supported"}


def test_set_labor_hook_validates_citizen_and_reports_before_after() -> None:
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "set_labor.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    # citizenship gate: not-found and non-citizen reasons, mirroring live facts
    assert "dfhack.units.isCitizen" in hook_text
    assert "unit_not_found" in hook_text
    assert "not_a_citizen" in hook_text
    # evidence-honest before/after enabled state + no-op visibility
    assert "labor_before" in hook_text
    assert "labor_after" in hook_text
    assert "labor_changed" in hook_text
    # flips exactly the labor flag, the v-p-l mechanic
    assert "status.labors[labor_enum] = enable" in hook_text
    # enum guarded on this DF build, reported honestly rather than crashing
    assert "unsupported_labor" in hook_text
    assert "df.unit_labor[enum_name]" in hook_text
    # CP437 safety on any DF-sourced text
    assert "gsub('[^%w %p]', '?')" in hook_text


def test_set_labor_hook_whitelists_exact_labor_enums() -> None:
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "set_labor.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    # whitelist mirrors dfhack_backend.LABOR_WHITELIST enum names exactly
    for enum_name in dfhack_backend.LABOR_WHITELIST.values():
        assert enum_name in hook_text


def test_set_labor_wraps_bounded_lua_hook(monkeypatch) -> None:
    captured: dict = {}

    def fake_run_lua_file(path, *args, **kwargs):
        captured["path"] = path
        captured["args"] = args
        return {"ok": True, "unit_id": 243, "labor": "brewing", "labor_changed": True}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run_lua_file)

    result = dfhack_backend.set_labor(243, "brewing", True)

    assert result["labor_changed"] is True
    assert captured["args"] == ("243", "brewing", "1")
    assert Path(captured["path"]).name == "set_labor.lua"


def test_set_labor_passes_enable_false_as_zero(monkeypatch) -> None:
    captured: dict = {}

    def fake_run_lua_file(path, *args, **kwargs):
        captured["args"] = args
        return {"ok": True}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run_lua_file)

    dfhack_backend.set_labor(248, "mine", False)

    assert captured["args"] == ("248", "mine", "0")


def test_set_labor_rejects_non_whitelisted_labor() -> None:
    result = dfhack_backend.set_labor(243, "engraving", True)

    assert result == {"ok": False, "error": "unsupported_labor", "labor": "engraving"}


def test_job_metrics_hook_emits_per_citizen_list() -> None:
    hook_path = Path(__file__).resolve().parents[1] / "hook" / "job_metrics.lua"
    hook_text = hook_path.read_text(encoding="utf-8")

    # per-citizen detail (id + enabled whitelist labors + current job), capped
    assert "MAX_CITIZEN_ENTRIES = 20" in hook_text
    assert "citizen_enabled_labors" in hook_text
    assert "current_job_type" in hook_text
    assert "list = {}" in hook_text
    # aggregate counts kept for backward compatibility
    assert "mining_labor = 0" in hook_text
    assert "carpentry_labor = 0" in hook_text


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


def test_job_metrics_reports_farm_plots_count() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "hook" / "job_metrics.lua"
    ).read_text(encoding="utf-8")

    assert "out.farm_plots" in script
    assert "out.farm_plot_positions" in script
    assert "df.building_type.FarmPlot" in script
    assert "flags.designated = true" not in script


def test_job_metrics_splits_true_shrub_count_from_other_tiles() -> None:
    # shrub_or_other lumps true SHRUB-shape tiles together with unrelated
    # terrain (boulders, pebbles, fortifications, ramps). A separate `shrub`
    # count lets callers report how many of those tiles are actually
    # gatherable rather than attaching gather-ability to the combined count.
    script = (
        Path(__file__).resolve().parents[1] / "hook" / "job_metrics.lua"
    ).read_text(encoding="utf-8")
    assert "counts.shrub = counts.shrub + 1" in script
    assert "shape_name == 'SHRUB'" in script
    assert "shrub = counts.shrub," in script


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


def test_read_game_state_counts_dead_citizens_for_real() -> None:
    """G6 attempt 1 (run 769f5034): a citizen drowned, pop dropped 7->6, and
    the dead metric never moved — state.dead was hardcoded 0. The state
    script must actually count our civ's dead dwarves."""
    import inspect

    from fort_gym.bench import dfhack_exec

    source = inspect.getsource(dfhack_exec.read_game_state)
    assert "state.dead = 0" not in source
    assert "dfhack.units.isDead(unit)" in source
    assert "state.dead = dead_count" in source


def test_fort_metrics_reports_nearby_tree_clusters() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "hook" / "fort_metrics.lua"
    ).read_text(encoding="utf-8")
    # clearing spawns: the fort window can hold zero trunks while forests
    # stand 20 tiles away — the scan is factual content, bounded, read-only
    assert "nearby_trees" in script
    assert "local RADIUS = 40" in script
    assert "table.sort(list" in script


def test_read_game_state_reports_usable_stock_counts() -> None:
    """The build hooks can only consume unclaimed items; the state script
    must report usable counts with the same filter (in_job / in_building /
    construction / forbid / hidden all lock an item)."""
    import inspect

    from fort_gym.bench import dfhack_exec

    source = inspect.getsource(dfhack_exec.read_game_state)
    assert "wood_usable" in source
    assert "stone_usable" in source
    assert "item.flags.in_job" in source
    assert "item.flags.in_building" in source

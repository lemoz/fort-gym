from __future__ import annotations

from pathlib import Path

HOOK_SOURCE = (Path(__file__).resolve().parents[1] / "hook" / "job_metrics.lua").read_text(
    encoding="utf-8"
)
G7_EVIDENCE_SOURCE = (Path(__file__).resolve().parents[1] / "hook" / "g7_evidence.lua").read_text(
    encoding="utf-8"
)


def test_g7_citizen_filter_propagates_classifier_failures() -> None:
    citizen_filter = G7_EVIDENCE_SOURCE.split("local function is_run_citizen", 1)[1].split(
        "local function unit_is_dead", 1
    )[0]
    assert "dfhack.units.isCitizen(unit, true)" in citizen_filter
    assert G7_EVIDENCE_SOURCE.count("dfhack.units.isCitizen(unit, true)") == 1
    assert "civ_dwarf" not in G7_EVIDENCE_SOURCE
    assert "pcall" not in citizen_filter
    assert "and true or false" in citizen_filter
    assert "unit.civ_id" not in G7_EVIDENCE_SOURCE
    assert "dfhack.units.isDwarf(unit)" not in G7_EVIDENCE_SOURCE

    dead_filter = G7_EVIDENCE_SOURCE.split("local function unit_is_dead", 1)[1].split(
        "local function history_signatures", 1
    )[0]
    assert "dfhack.units.isDead(unit)" in dead_filter
    assert "pcall" not in dead_filter


def test_g7_citizen_filter_is_used_for_every_membership_sensitive_path() -> None:
    scan_consumption = G7_EVIDENCE_SOURCE.split("local function scan_consumption", 1)[1].split(
        "local function raw_value", 1
    )[0]
    record_death = G7_EVIDENCE_SOURCE.split("local function record_death", 1)[1].split(
        "local function scan_deaths", 1
    )[0]
    scan_deaths = G7_EVIDENCE_SOURCE.split("local function scan_deaths", 1)[1].split(
        "local function item_on_completed_farm_plot", 1
    )[0]
    baseline = G7_EVIDENCE_SOURCE.split("if command == 'start'", 1)[1].split(
        "scan_consumption(ledger, true)", 1
    )[0]
    callback = G7_EVIDENCE_SOURCE.split(
        "eventful.onUnitDeath[CALLBACK_KEY] = function(unit_id)", 1
    )[1].split("eventful.enableEvent", 1)[0]

    for path in (scan_consumption, record_death, scan_deaths, baseline):
        assert "is_run_citizen(unit)" in path
    assert "pcall(record_death, active, unit)" in callback
    assert "ledger.flow_evidence_complete = false" in scan_deaths
    assert "ledger.death_evidence_complete = false" in scan_deaths
    assert callback.count("active.flow_evidence_complete = false") == 2
    assert callback.count("active.death_evidence_complete = false") == 2
    assert "local baseline_ok = pcall(function()" in baseline
    assert "ledger.death_evidence_complete = false" in baseline
    assert "baseline_dead_citizen_scan_failed" in baseline


def test_job_metrics_separates_completed_furniture_from_all_placed_furniture() -> None:
    assert "out.placed_furniture_completed" in HOOK_SOURCE
    assert "local function building_stage(bld)" in HOOK_SOURCE
    assert "max_stage > 0" in HOOK_SOURCE
    assert "return true, stage, max_stage, stage >= max_stage" in HOOK_SOURCE
    assert "out.placed_furniture[key] = out.placed_furniture[key] + 1" in HOOK_SOURCE
    assert (
        "out.placed_furniture_completed[key] = out.placed_furniture_completed[key] + 1"
        in HOOK_SOURCE
    )


def test_job_metrics_collects_bounded_raw_farm_contained_item_evidence() -> None:
    for needle in (
        "MAX_FARM_PLOT_DETAILS = 8",
        "MAX_FARM_PLOT_CONTAINED_ITEMS = 25",
        "out.farm_plot_details_truncated = false",
        "contained_items_read_ok = contained_items_read_ok",
        "contained_items_truncated = contained_items_truncated",
        "read_ok = false",
        "item_type = false",
        "item_id = false",
        "use_mode = false",
        "mat_index = false",
        "grow_counter = false",
        "planting_skill = false",
        "mat_token = false",
        "mat_token_read_ok = false",
        "_plant_raws[mat_index].id",
        "#records >= MAX_FARM_PLOT_CONTAINED_ITEMS",
        "if not record.read_ok then read_ok = false end",
    ):
        assert needle in HOOK_SOURCE
    assert "world.plants.all" not in HOOK_SOURCE
    for heuristic_label in (
        "is_growing",
        "pathing_blocked",
        "percent",
        "inferred status",
    ):
        assert heuristic_label not in HOOK_SOURCE


def test_job_metrics_emits_raw_dead_citizen_observability_without_inference() -> None:
    dead_observability = HOOK_SOURCE.split("out.dead_citizen_count = 0", 1)[1].split(
        "-- optional bounded rect tile composition", 1
    )[0]
    dead_scan = dead_observability.split("local dead_scan_ok = pcall(function()", 1)[1].split(
        "-- A failed record must fail closed", 1
    )[0]
    for needle in (
        "df.global.world.units.all",
        "out.dead_citizen_records",
        "unit_id = unit_id",
        "cause_enum = cause_enum",
        "cause_name = cause_name",
        "cause_known = cause_known",
        "incident_id = dead_value(unit, 'counters', 'death_id')",
        "hunger_timer = dead_value(unit, 'counters2', 'hunger_timer')",
        "thirst_timer = dead_value(unit, 'counters2', 'thirst_timer')",
        "stored_fat = dead_value(unit, 'counters2', 'stored_fat')",
        "stomach_food = dead_value(unit, 'counters2', 'stomach_food')",
        "drowning = dead_flag(unit, 'flags1', 'drowning')",
        "suffocation = dead_value(unit, 'counters', 'suffocation')",
        "emotionally_overloaded = dead_flag(unit, 'flags3', 'emotionally_overloaded')",
        "df.death_type[cause_number]",
        "pcall(function()",
    ):
        assert needle in dead_observability

    assert "dfhack.units.isCitizen(unit, true)" in dead_scan
    assert "and dfhack.units.isDead(unit)" in dead_scan
    assert "local ok_dead" not in dead_scan
    assert "unit.civ_id == civ_id" not in dead_scan
    assert "dfhack.units.isDwarf(unit)" not in dead_scan
    assert "neglect_deaths" not in dead_observability


def test_death_hooks_keep_current_drowning_flag_separate_from_known_cause() -> None:
    for source in (HOOK_SOURCE, G7_EVIDENCE_SOURCE):
        assert "cause_name = 'DROWNING'" not in source
        assert "cause_source = 'flags1.drowning'" not in source
        assert "current-condition flag" in source
        assert "cause_source = cause_source" in source


def test_job_metrics_preserves_raw_unset_death_cause_enum() -> None:
    assert "if cause_number then cause_enum = cause_number end" in HOOK_SOURCE


def test_job_metrics_fails_closed_when_dead_record_evidence_is_incomplete() -> None:
    assert "out.dead_citizen_count = out.dead_citizen_count + 1" in HOOK_SOURCE
    assert "local dead_scan_ok = pcall(function()" in HOOK_SOURCE
    assert "and #out.dead_citizen_records == out.dead_citizen_count" in HOOK_SOURCE
    assert (
        "out.death_causes_known = out.death_evidence_complete and all_causes_known" in HOOK_SOURCE
    )

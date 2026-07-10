from __future__ import annotations

from pathlib import Path

HOOK_SOURCE = (Path(__file__).resolve().parents[1] / "hook" / "job_metrics.lua").read_text(
    encoding="utf-8"
)
G7_EVIDENCE_SOURCE = (Path(__file__).resolve().parents[1] / "hook" / "g7_evidence.lua").read_text(
    encoding="utf-8"
)


def test_g7_citizen_filter_returns_one_boolean_value() -> None:
    citizen_filter = G7_EVIDENCE_SOURCE.split("local function civ_dwarf", 1)[1].split(
        "local function unit_is_dead", 1
    )[0]
    assert "return ok and result or false" in citizen_filter
    assert "return ok, ok and result or false" not in citizen_filter


def test_job_metrics_separates_completed_furniture_from_all_placed_furniture() -> None:
    assert "out.placed_furniture_completed" in HOOK_SOURCE
    assert "bld:getBuildStage() >= bld:getMaxBuildStage()" in HOOK_SOURCE
    assert "out.placed_furniture[key] = out.placed_furniture[key] + 1" in HOOK_SOURCE
    assert (
        "out.placed_furniture_completed[key] = out.placed_furniture_completed[key] + 1"
        in HOOK_SOURCE
    )


def test_job_metrics_emits_raw_dead_citizen_observability_without_inference() -> None:
    for needle in (
        "df.global.world.units.all",
        "unit.civ_id == civ_id",
        "dfhack.units.isDwarf(unit)",
        "dfhack.units.isDead(unit)",
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
        assert needle in HOOK_SOURCE

    assert "neglect_deaths" not in HOOK_SOURCE


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

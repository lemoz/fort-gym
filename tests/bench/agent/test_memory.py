from __future__ import annotations

from fort_gym.bench.agent.memory import MemoryManager


def test_memory_context_empty() -> None:
    memory = MemoryManager()
    assert memory.get_context() == ""


def test_memory_window_zero_disables_memory() -> None:
    memory = MemoryManager(window_size=0)
    memory.add_step("obs one", {"type": "KEYSTROKE", "params": {"keys": ["A"]}}, "res one")

    assert memory.get_context() == ""
    assert memory.summary == ""
    assert memory.recent_steps == []


def test_memory_window_and_summary() -> None:
    memory = MemoryManager(window_size=2, summary_max_chars=500, step_max_chars=80)
    memory.add_step("obs one", {"type": "KEYSTROKE", "params": {"keys": ["A"]}}, "res one")
    memory.add_step("obs two", {"type": "KEYSTROKE", "params": {"keys": ["B"]}}, "res two")

    assert memory.summary == ""
    assert len(memory.recent_steps) == 2

    memory.add_step("obs three", {"type": "KEYSTROKE", "params": {"keys": ["C"]}}, "res three")

    assert len(memory.recent_steps) == 2
    assert "Step 1" in memory.summary

    context = memory.get_context()
    assert "Summary:" in context
    assert "Recent Steps:" in context
    assert "Step 1" in context
    assert "Step 2" in context
    assert "Step 3" in context


def test_summary_truncation() -> None:
    memory = MemoryManager(window_size=1, summary_max_chars=20, step_max_chars=200)
    memory.add_step("obs one", {"type": "KEYSTROKE", "params": {"keys": ["A"]}}, "res one")
    memory.add_step("obs two", {"type": "KEYSTROKE", "params": {"keys": ["B"]}}, "res two")

    assert memory.summary
    assert len(memory.summary) <= 20


def test_summary_keeps_latest_overflow() -> None:
    memory = MemoryManager(window_size=1, summary_max_chars=100, step_max_chars=40)
    memory.add_step("obs one", {"type": "KEYSTROKE", "params": {"keys": ["A"]}}, "res one")
    memory.add_step("obs two", {"type": "KEYSTROKE", "params": {"keys": ["B"]}}, "res two")
    memory.add_step("obs three", {"type": "KEYSTROKE", "params": {"keys": ["C"]}}, "res three")

    assert "Step 2" in memory.summary


def test_memory_records_and_queries_pois() -> None:
    memory = MemoryManager(window_size=2)

    result = memory.remember_poi(
        label="carpenter workshop",
        kind="building",
        x=99,
        y=96,
        z=177,
        status="built",
        evidence="carpenter_workshops increased",
    )

    assert "Remembered POI" in result
    context = memory.get_context()
    assert "Known POIs:" in context
    assert "carpenter workshop" in context
    assert "coords=(99,96,177)" in context

    query = memory.query_memory(query="carpenter", kind="building", near=[100, 96, 177])
    assert "carpenter workshop" in query
    assert "status=built" in query


def test_memory_records_failed_attempts() -> None:
    memory = MemoryManager(window_size=2)

    result = memory.remember_failed_attempt(
        label="craftsdwarf placement",
        reason="no building or job appeared",
        x=101,
        y=100,
        z=177,
        evidence="actual_ticks=0 and changed=none",
    )

    assert "Remembered failed attempt" in result
    query = memory.query_memory(query="craftsdwarf")
    assert "Failed attempts:" in query
    assert "craftsdwarf placement" in query
    assert "no building or job appeared" in query


def test_memory_tracks_gameplay_plan_and_reviews() -> None:
    memory = MemoryManager(window_size=2)

    plan_result = memory.write_gameplay_plan(
        objective="complete useful fortress space",
        phase="post-workshop",
        steps=["confirm workshop exists", "finish planned room", "create stockpile"],
        current_step="finish planned room",
        reason="workshop loop has already succeeded",
        evidence="carpenter_workshops=1",
    )

    assert "Gameplay plan written" in plan_result
    context = memory.get_context()
    assert "Gameplay Plan:" in context
    assert "complete useful fortress space" in context
    assert "finish planned room" in context

    review_result = memory.review_gameplay_plan(
        status="needs_revision",
        evidence="no_progress_streak=2",
        completed_steps=["confirm workshop exists"],
        blockers=["repeating workshop placement"],
        next_step="designate a new room area",
        revised_steps=["exit build menu", "designate a new room area"],
        reason="shift away from workshop loop",
    )

    assert "Reviewed gameplay plan" in review_result
    context = memory.get_context()
    assert "Recent Plan Reviews:" in context
    assert "repeating workshop placement" in context
    assert "designate a new room area" in context

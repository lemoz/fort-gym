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

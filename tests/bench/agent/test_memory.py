from __future__ import annotations

from fort_gym.bench.agent.memory import MemoryManager


def test_memory_context_empty() -> None:
    memory = MemoryManager()
    assert memory.get_context() == ""


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

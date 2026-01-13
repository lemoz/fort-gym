"""Hybrid memory manager for agent step history."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Sequence


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _truncate_head(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


def _truncate_tail(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    if limit <= 3:
        return text[-limit:]
    return "..." + text[-(limit - 3) :]


def _format_action(action: Dict[str, Any]) -> str:
    try:
        return json.dumps(action, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(action)


@dataclass(frozen=True)
class StepRecord:
    step: int
    observation: str
    action: Dict[str, Any]
    result: str

    def to_line(self, max_chars: int) -> str:
        obs_text = _truncate_head(_normalize_text(self.observation), max_chars)
        action_text = _truncate_head(_normalize_text(_format_action(self.action)), max_chars)
        result_text = _truncate_head(_normalize_text(self.result), max_chars)
        return (
            f"Step {self.step}: obs={obs_text} "
            f"action={action_text} result={result_text}"
        )


SummaryFn = Callable[[str, Sequence[StepRecord]], str]


class MemoryManager:
    """Maintain recent steps while summarizing older history."""

    def __init__(
        self,
        window_size: int = 10,
        summary_max_chars: int = 2000,
        step_max_chars: int = 240,
        summarizer: SummaryFn | None = None,
    ) -> None:
        if window_size <= 0:
            raise ValueError("window_size must be >= 1")
        self.window_size = window_size
        self.summary_max_chars = summary_max_chars
        self.step_max_chars = step_max_chars
        self.recent_steps: List[StepRecord] = []
        self.summary = ""
        self._step_counter = 0
        self._summarizer = summarizer or self._default_summarizer

    def add_step(self, observation: str, action: Dict[str, Any], result: str) -> None:
        self._step_counter += 1
        record = StepRecord(
            step=self._step_counter,
            observation=observation,
            action=dict(action),
            result=result,
        )
        self.recent_steps.append(record)
        self.compress_old_steps()

    def get_context(self) -> str:
        if not self.summary and not self.recent_steps:
            return ""
        lines = ["== MEMORY =="]
        if self.summary:
            lines.extend(["Summary:", self.summary])
        if self.recent_steps:
            lines.append("Recent Steps:")
            lines.extend(step.to_line(self.step_max_chars) for step in self.recent_steps)
        return "\n".join(lines).strip()

    def compress_old_steps(self) -> None:
        if len(self.recent_steps) <= self.window_size:
            return
        overflow = self.recent_steps[:-self.window_size]
        self.summary = self._summarizer(self.summary, overflow).strip()
        if self.summary_max_chars > 0:
            self.summary = _truncate_tail(self.summary, self.summary_max_chars)
        self.recent_steps = self.recent_steps[-self.window_size :]

    def _default_summarizer(self, current_summary: str, steps: Sequence[StepRecord]) -> str:
        lines: List[str] = []
        if current_summary:
            lines.append(current_summary.strip())
        lines.extend(step.to_line(self.step_max_chars) for step in steps)
        return "\n".join(line for line in lines if line).strip()


__all__ = ["MemoryManager", "StepRecord"]

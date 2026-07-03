"""Hybrid memory manager for agent step history."""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import sqrt
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
        max_pois: int = 40,
        max_failed_attempts: int = 40,
        summarizer: SummaryFn | None = None,
    ) -> None:
        if window_size < 0:
            raise ValueError("window_size must be >= 0")
        self.window_size = window_size
        self._enabled = window_size > 0
        self.summary_max_chars = summary_max_chars
        self.step_max_chars = step_max_chars
        self.max_pois = max(0, max_pois)
        self.max_failed_attempts = max(0, max_failed_attempts)
        self.recent_steps: List[StepRecord] = []
        self.pois: List[Dict[str, Any]] = []
        self.failed_attempts: List[Dict[str, Any]] = []
        self.gameplay_plan: Dict[str, Any] = {}
        self.plan_reviews: List[Dict[str, Any]] = []
        self.summary = ""
        self._step_counter = 0
        self._summarizer = summarizer or self._default_summarizer

    def add_step(self, observation: str, action: Dict[str, Any], result: str) -> None:
        if not self._enabled:
            return
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
        if not self._enabled:
            return ""
        if (
            not self.summary
            and not self.recent_steps
            and not self.pois
            and not self.failed_attempts
            and not self.gameplay_plan
            and not self.plan_reviews
        ):
            return ""
        lines = ["== MEMORY =="]
        if self.summary:
            lines.extend(["Summary:", self.summary])
        if self.pois:
            lines.append("Known POIs:")
            lines.extend(self._format_poi_line(poi) for poi in self.pois[-10:])
        if self.failed_attempts:
            lines.append("Recent Failed Attempts:")
            lines.extend(self._format_failed_attempt_line(item) for item in self.failed_attempts[-10:])
        if self.gameplay_plan:
            lines.append("Gameplay Plan:")
            lines.append(self._format_gameplay_plan(self.gameplay_plan))
        if self.plan_reviews:
            lines.append("Recent Plan Reviews:")
            lines.extend(self._format_plan_review_line(item) for item in self.plan_reviews[-5:])
        if self.recent_steps:
            lines.append("Recent Steps:")
            lines.extend(step.to_line(self.step_max_chars) for step in self.recent_steps)
        return "\n".join(lines).strip()

    def remember_poi(
        self,
        *,
        label: str,
        kind: str = "",
        x: Any = None,
        y: Any = None,
        z: Any = None,
        status: str = "",
        evidence: str = "",
    ) -> str:
        """Store or update an agent-discovered point of interest."""

        if not self._enabled:
            return "Memory is disabled."
        clean_label = _normalize_text(str(label)).strip()
        if not clean_label:
            return "POI label is required."
        poi = {
            "label": _truncate_head(clean_label, 80),
            "kind": _truncate_head(_normalize_text(str(kind)).strip(), 40),
            "status": _truncate_head(_normalize_text(str(status)).strip(), 80),
            "evidence": _truncate_head(_normalize_text(str(evidence)).strip(), 180),
        }
        coords = self._clean_coords(x, y, z)
        if coords is not None:
            poi.update({"x": coords[0], "y": coords[1], "z": coords[2]})

        existing_index = self._find_poi_index(poi)
        if existing_index is not None:
            self.pois[existing_index] = {**self.pois[existing_index], **poi}
            self._move_poi_to_end(existing_index)
            return "Updated POI: " + self._format_poi_line(self.pois[-1])

        self.pois.append(poi)
        if self.max_pois and len(self.pois) > self.max_pois:
            self.pois = self.pois[-self.max_pois :]
        return "Remembered POI: " + self._format_poi_line(poi)

    def remember_failed_attempt(
        self,
        *,
        label: str,
        reason: str = "",
        x: Any = None,
        y: Any = None,
        z: Any = None,
        evidence: str = "",
    ) -> str:
        """Store an agent-discovered location or action to avoid repeating."""

        if not self._enabled:
            return "Memory is disabled."
        clean_label = _normalize_text(str(label)).strip()
        if not clean_label:
            return "Failed-attempt label is required."
        item = {
            "label": _truncate_head(clean_label, 80),
            "reason": _truncate_head(_normalize_text(str(reason)).strip(), 120),
            "evidence": _truncate_head(_normalize_text(str(evidence)).strip(), 180),
        }
        coords = self._clean_coords(x, y, z)
        if coords is not None:
            item.update({"x": coords[0], "y": coords[1], "z": coords[2]})

        self.failed_attempts.append(item)
        if self.max_failed_attempts and len(self.failed_attempts) > self.max_failed_attempts:
            self.failed_attempts = self.failed_attempts[-self.max_failed_attempts :]
        return "Remembered failed attempt: " + self._format_failed_attempt_line(item)

    def write_gameplay_plan(
        self,
        *,
        objective: str,
        phase: str = "",
        steps: Sequence[Any] | None = None,
        current_step: str = "",
        reason: str = "",
        evidence: str = "",
    ) -> str:
        """Store the agent's current multi-step gameplay plan."""

        if not self._enabled:
            return "Memory is disabled."
        clean_objective = _normalize_text(str(objective)).strip()
        if not clean_objective:
            return "Gameplay plan objective is required."
        clean_steps = [
            _truncate_head(_normalize_text(str(step)).strip(), 140)
            for step in (steps or [])
            if _normalize_text(str(step)).strip()
        ]
        self.gameplay_plan = {
            "objective": _truncate_head(clean_objective, 160),
            "phase": _truncate_head(_normalize_text(str(phase)).strip(), 80),
            "steps": clean_steps[:8],
            "current_step": _truncate_head(_normalize_text(str(current_step)).strip(), 120),
            "reason": _truncate_head(_normalize_text(str(reason)).strip(), 160),
            "evidence": _truncate_head(_normalize_text(str(evidence)).strip(), 180),
            "revision": int(self.gameplay_plan.get("revision") or 0) + 1,
        }
        return "Gameplay plan written: " + self._format_gameplay_plan(self.gameplay_plan)

    def review_gameplay_plan(
        self,
        *,
        status: str,
        evidence: str = "",
        completed_steps: Sequence[Any] | None = None,
        blockers: Sequence[Any] | None = None,
        next_step: str = "",
        revised_steps: Sequence[Any] | None = None,
        reason: str = "",
    ) -> str:
        """Record a plan review and optionally revise the stored plan steps."""

        if not self._enabled:
            return "Memory is disabled."
        if not self.gameplay_plan:
            return "No gameplay plan exists. Call write_gameplay_plan first."
        clean_status = _normalize_text(str(status)).strip()
        if not clean_status:
            return "Plan review status is required."
        completed = [
            _truncate_head(_normalize_text(str(step)).strip(), 120)
            for step in (completed_steps or [])
            if _normalize_text(str(step)).strip()
        ]
        blocker_items = [
            _truncate_head(_normalize_text(str(blocker)).strip(), 120)
            for blocker in (blockers or [])
            if _normalize_text(str(blocker)).strip()
        ]
        clean_revised_steps = [
            _truncate_head(_normalize_text(str(step)).strip(), 140)
            for step in (revised_steps or [])
            if _normalize_text(str(step)).strip()
        ]
        clean_next_step = _truncate_head(_normalize_text(str(next_step)).strip(), 120)
        review = {
            "status": _truncate_head(clean_status, 60),
            "evidence": _truncate_head(_normalize_text(str(evidence)).strip(), 180),
            "completed_steps": completed[:6],
            "blockers": blocker_items[:6],
            "next_step": clean_next_step,
            "reason": _truncate_head(_normalize_text(str(reason)).strip(), 160),
        }
        self.plan_reviews.append(review)
        if len(self.plan_reviews) > 20:
            self.plan_reviews = self.plan_reviews[-20:]
        if clean_revised_steps:
            self.gameplay_plan = {
                **self.gameplay_plan,
                "steps": clean_revised_steps[:8],
                "current_step": clean_next_step,
                "reason": review["reason"],
                "evidence": review["evidence"],
                "revision": int(self.gameplay_plan.get("revision") or 0) + 1,
            }
        elif clean_next_step:
            self.gameplay_plan = {
                **self.gameplay_plan,
                "current_step": clean_next_step,
                "evidence": review["evidence"],
            }
        return (
            "Reviewed gameplay plan: "
            + self._format_plan_review_line(review)
            + "\nCurrent plan: "
            + self._format_gameplay_plan(self.gameplay_plan)
        )

    def query_memory(
        self,
        *,
        query: str = "",
        kind: str = "",
        near: Sequence[Any] | None = None,
        include_failed: bool = True,
        limit: int = 5,
    ) -> str:
        """Return remembered POIs and failed attempts relevant to the query."""

        if not self._enabled:
            return "Memory is disabled."
        limit = max(1, min(int(limit or 5), 10))
        query_tokens = set(_normalize_text(str(query)).lower().split())
        kind_text = _normalize_text(str(kind)).lower().strip()
        near_coords = self._clean_coords(*(near or [])) if near else None

        scored_pois: List[tuple[float, Dict[str, Any]]] = []
        for index, poi in enumerate(self.pois):
            if kind_text and kind_text not in str(poi.get("kind", "")).lower():
                continue
            score = float(index) * 0.001
            searchable = " ".join(
                str(poi.get(key, "")) for key in ("label", "kind", "status", "evidence")
            ).lower()
            query_matches = not query_tokens or bool(query_tokens & set(searchable.split()))
            if not query_matches and not near_coords:
                continue
            if query_tokens:
                score += len(query_tokens & set(searchable.split()))
            if near_coords and self._has_coords(poi):
                distance = self._distance(near_coords, (poi["x"], poi["y"], poi["z"]))
                score += max(0.0, 1000.0 - distance)
            if query_tokens or kind_text or near_coords or score >= 0:
                scored_pois.append((score, poi))

        scored_pois.sort(key=lambda item: item[0], reverse=True)
        lines: List[str] = []
        if scored_pois:
            lines.append("Known POIs:")
            lines.extend(self._format_poi_line(poi) for _, poi in scored_pois[:limit])
        if include_failed and self.failed_attempts:
            lines.append("Failed attempts:")
            lines.extend(
                self._format_failed_attempt_line(item)
                for item in self.failed_attempts[-limit:]
            )
        if not lines:
            return "No matching memory entries."
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the cross-run-relevant parts of memory to a plain dict.

        Deliberately EXCLUDES ``recent_steps``: step records are scoped to a
        single run's observation/action/result history and are not meaningful
        replayed against a different run, even on the same seed save.
        """

        return {
            "summary": self.summary,
            "pois": [dict(poi) for poi in self.pois],
            "failed_attempts": [dict(item) for item in self.failed_attempts],
            "gameplay_plan": dict(self.gameplay_plan),
            "plan_reviews": [dict(item) for item in self.plan_reviews],
            "_step_counter": self._step_counter,
        }

    def load_dict(self, data: Dict[str, Any]) -> None:
        """Restore memory fields from a dict produced by ``to_dict``.

        Defensive by design: malformed or wrong-typed values are ignored in
        favor of the current defaults rather than raising, and list fields
        are clamped to the configured ``max_pois``/``max_failed_attempts``
        caps. ``recent_steps`` is never touched.
        """

        if not isinstance(data, dict):
            return

        summary = data.get("summary")
        if isinstance(summary, str):
            self.summary = summary

        pois = data.get("pois")
        if isinstance(pois, list):
            clean_pois = [item for item in pois if isinstance(item, dict)]
            if self.max_pois:
                clean_pois = clean_pois[-self.max_pois :]
            self.pois = clean_pois

        failed_attempts = data.get("failed_attempts")
        if isinstance(failed_attempts, list):
            clean_failed = [item for item in failed_attempts if isinstance(item, dict)]
            if self.max_failed_attempts:
                clean_failed = clean_failed[-self.max_failed_attempts :]
            self.failed_attempts = clean_failed

        gameplay_plan = data.get("gameplay_plan")
        if isinstance(gameplay_plan, dict):
            self.gameplay_plan = dict(gameplay_plan)

        plan_reviews = data.get("plan_reviews")
        if isinstance(plan_reviews, list):
            clean_reviews = [item for item in plan_reviews if isinstance(item, dict)]
            self.plan_reviews = clean_reviews[-20:]

        step_counter = data.get("_step_counter")
        if isinstance(step_counter, int) and not isinstance(step_counter, bool):
            self._step_counter = step_counter

    def compress_old_steps(self) -> None:
        if not self._enabled:
            return
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

    def _find_poi_index(self, poi: Dict[str, Any]) -> int | None:
        for index, existing in enumerate(self.pois):
            if existing.get("label") != poi.get("label"):
                continue
            if self._has_coords(existing) and self._has_coords(poi):
                if (
                    existing.get("x") == poi.get("x")
                    and existing.get("y") == poi.get("y")
                    and existing.get("z") == poi.get("z")
                ):
                    return index
                continue
            if existing.get("kind") == poi.get("kind"):
                return index
        return None

    def _move_poi_to_end(self, index: int) -> None:
        item = self.pois.pop(index)
        self.pois.append(item)

    @staticmethod
    def _clean_coords(*coords: Any) -> tuple[int, int, int] | None:
        if len(coords) < 3:
            return None
        try:
            return int(coords[0]), int(coords[1]), int(coords[2])
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _has_coords(item: Dict[str, Any]) -> bool:
        return all(key in item for key in ("x", "y", "z"))

    @staticmethod
    def _distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
        return sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)

    @staticmethod
    def _format_coords(item: Dict[str, Any]) -> str:
        if not MemoryManager._has_coords(item):
            return "coords=?"
        return f"coords=({item['x']},{item['y']},{item['z']})"

    @classmethod
    def _format_poi_line(cls, poi: Dict[str, Any]) -> str:
        parts = [
            f"- {poi.get('label', '?')}",
            f"kind={poi.get('kind') or '?'}",
            cls._format_coords(poi),
        ]
        if poi.get("status"):
            parts.append(f"status={poi['status']}")
        if poi.get("evidence"):
            parts.append(f"evidence={poi['evidence']}")
        return "; ".join(parts)

    @classmethod
    def _format_failed_attempt_line(cls, item: Dict[str, Any]) -> str:
        parts = [f"- {item.get('label', '?')}", cls._format_coords(item)]
        if item.get("reason"):
            parts.append(f"reason={item['reason']}")
        if item.get("evidence"):
            parts.append(f"evidence={item['evidence']}")
        return "; ".join(parts)

    @staticmethod
    def _format_gameplay_plan(plan: Dict[str, Any]) -> str:
        parts = [
            f"- objective={plan.get('objective', '?')}",
            f"phase={plan.get('phase') or '?'}",
            f"current={plan.get('current_step') or '?'}",
            f"revision={plan.get('revision') or 0}",
        ]
        steps = plan.get("steps")
        if isinstance(steps, list) and steps:
            parts.append("steps=" + " | ".join(str(step) for step in steps[:6]))
        if plan.get("reason"):
            parts.append(f"reason={plan['reason']}")
        if plan.get("evidence"):
            parts.append(f"evidence={plan['evidence']}")
        return "; ".join(parts)

    @staticmethod
    def _format_plan_review_line(review: Dict[str, Any]) -> str:
        parts = [f"- status={review.get('status', '?')}"]
        if review.get("next_step"):
            parts.append(f"next={review['next_step']}")
        blockers = review.get("blockers")
        if isinstance(blockers, list) and blockers:
            parts.append("blockers=" + ", ".join(str(item) for item in blockers[:4]))
        completed = review.get("completed_steps")
        if isinstance(completed, list) and completed:
            parts.append("completed=" + ", ".join(str(item) for item in completed[:4]))
        if review.get("evidence"):
            parts.append(f"evidence={review['evidence']}")
        if review.get("reason"):
            parts.append(f"reason={review['reason']}")
        return "; ".join(parts)


__all__ = ["MemoryManager", "StepRecord"]

"""Tooling support for agent tool use."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from .memory import MemoryManager


_WORD_RE = re.compile(r"[a-z0-9]+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _tokenize(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


def _excerpt(text: str, query_tokens: set[str], limit: int) -> str:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return ""
    sentences = _SENTENCE_RE.split(cleaned)
    for index, sentence in enumerate(sentences):
        if query_tokens & _tokenize(sentence):
            context = " ".join(sentences[index:])
            return _truncate(context, limit)
    return _truncate(sentences[0], limit)


@dataclass(frozen=True)
class WikiDoc:
    title: str
    body: str
    keywords: tuple[str, ...]


DEFAULT_DF_WIKI_DOCS: List[WikiDoc] = [
    WikiDoc(
        title="Designations and digging",
        body=(
            "Designations mark tiles for digging, channeling, stairs, or chopping. "
            "From the main view press d for designations, then choose d for mine, "
            "h for channel, u or j for stairs, or t for chop. Move the cursor, press "
            "select to start a rectangle, move again, press select to confirm. "
            "Digging works on soil or stone; if you only see trees or grass, move "
            "down a z level to reach stone. Use x in the designation menu to remove a mark."
        ),
        keywords=(
            "dig",
            "designate",
            "designation",
            "designations",
            "mine",
            "channel",
            "stairs",
            "chop",
            "cursor",
        ),
    ),
    WikiDoc(
        title="Buildings and workshops",
        body=(
            "D_BUILDJOB opens an existing selected workshop; BUILDJOB_ADD opens "
            "that workshop's native task list; SELECT picks the highlighted "
            "row. If the add-task list footer says '+-*/: Scroll', use "
            "STANDARDSCROLL_DOWN/STANDARDSCROLL_UP to move row selection; "
            "CURSOR_DOWN/CURSOR_UP can move the map cursor off the workshop. "
            "Parenthesized letters may be visible labels rather than "
            "reliable raw STRING_A hotkeys. In visible add-task lists, count rows "
            "from the top/highlighted item to the desired job, use repeated "
            "STANDARDSCROLL_DOWN or STANDARDSCROLL_UP to move the selected row, "
            "then press SELECT. "
            "The build menu b lets you place workshops, furnaces, and furniture. "
            "Choose the category and place on clear floor tiles. Most workshops need "
            "materials nearby and a dwarf with the matching labor. Carpenters make "
            "beds and barrels, while masons make stone blocks and furniture. "
            "If placement is blocked, check for walls, ramps, or items on the tile. "
            "Only a concrete selected task plus elapsed ticks can produce items."
        ),
        keywords=(
            "build",
            "building",
            "workshop",
            "furnace",
            "furniture",
            "carpenter",
            "mason",
            "buildjob",
            "buildjob_add",
            "task",
        ),
    ),
    WikiDoc(
        title="Manager orders and standing orders",
        body=(
            "Manager orders use D_JOBLIST then UNITJOB_MANAGER, followed by "
            "MANAGER_NEW_ORDER on the manager screen, to queue jobs like bed, "
            "door, table, chair, barrel, or bin in bulk. Assign a manager noble "
            "if the manager screen is unavailable: use D_NOBLES, not raw "
            "STRING_A110, to open Nobles and Administrators. On Nobles, no "
            "scroll/fixed counts; verify Manager row highlight first before SELECT. "
            "If dwarves "
            "do not take a workshop job, verify the visible workshop task, "
            "materials, cancellation text, and elapsed ticks before changing "
            "objectives. Do not switch into unit/labor menus unless the screen "
            "explicitly exposes a supported labor control. "
            "Standing orders (o) toggle hauling, refuse, and "
            "auto collect. If jobs do not start, check labor assignments and materials."
        ),
        keywords=(
            "manager",
            "orders",
            "order",
            "work",
            "workorder",
            "workorders",
            "unitjob",
            "unitjob_manager",
            "manager_new_order",
            "d_nobles",
            "d_unitlist",
            "nobles",
            "d_joblist",
            "jobs",
            "standing",
            "labor",
            "materials",
            "furniture",
            "bed",
            "door",
            "table",
            "chair",
            "barrel",
            "bin",
        ),
    ),
]


DF_WIKI_TOOL_SPEC: Dict[str, Any] = {
    "name": "df_wiki",
    "description": "Look up Dwarf Fortress gameplay rules from embedded wiki notes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Question about Dwarf Fortress mechanics or commands.",
            }
        },
        "required": ["question"],
    },
}

REMEMBER_POI_TOOL_SPEC: Dict[str, Any] = {
    "name": "remember_poi",
    "description": (
        "Remember a Dwarf Fortress point of interest that you discovered, such as "
        "a building, dwarf cluster, resource patch, stair, room, or blocked area."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "label": {"type": "string", "description": "Short human-readable name."},
            "kind": {
                "type": "string",
                "description": "POI category, e.g. building, unit, resource, room, blocked_tile.",
            },
            "x": {"type": "integer", "description": "Map x coordinate, if known."},
            "y": {"type": "integer", "description": "Map y coordinate, if known."},
            "z": {"type": "integer", "description": "Map z coordinate, if known."},
            "status": {
                "type": "string",
                "description": "Current known status, e.g. built, queued, blocked, visible.",
            },
            "evidence": {
                "type": "string",
                "description": "Brief evidence from screen or read-only state.",
            },
        },
        "required": ["label"],
    },
}

REMEMBER_FAILED_ATTEMPT_TOOL_SPEC: Dict[str, Any] = {
    "name": "remember_failed_attempt",
    "description": (
        "Remember an attempted placement/navigation/menu action that did not change "
        "tracked DF state, including failed native menu search terms, so you can "
        "avoid repeating it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "label": {
                "type": "string",
                "description": "Short name for the failed attempt; include menu and exact search term when relevant.",
            },
            "reason": {"type": "string", "description": "Why this attempt appears unproductive."},
            "x": {"type": "integer", "description": "Map x coordinate, if known."},
            "y": {"type": "integer", "description": "Map y coordinate, if known."},
            "z": {"type": "integer", "description": "Map z coordinate, if known."},
            "evidence": {"type": "string", "description": "Brief evidence from screen or state."},
        },
        "required": ["label"],
    },
}

QUERY_MEMORY_TOOL_SPEC: Dict[str, Any] = {
    "name": "query_memory",
    "description": (
        "Search your remembered POIs and failed attempts before retrying navigation, "
        "placement, inspection work, or native menu search terms."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search text."},
            "kind": {"type": "string", "description": "Optional POI category filter."},
            "near": {
                "type": "array",
                "description": "Optional [x, y, z] coordinate to search near.",
                "items": {"type": "integer"},
                "minItems": 3,
                "maxItems": 3,
            },
            "include_failed": {
                "type": "boolean",
                "description": "Whether to include failed attempts in the result.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum entries to return.",
                "minimum": 1,
                "maximum": 10,
            },
        },
    },
}

WRITE_GAMEPLAY_PLAN_TOOL_SPEC: Dict[str, Any] = {
    "name": "write_gameplay_plan",
    "description": (
        "Write or revise your current multi-step Dwarf Fortress gameplay plan. "
        "This is only notebook memory; it does not act in the game."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "objective": {"type": "string", "description": "Overall fortress objective."},
            "phase": {
                "type": "string",
                "description": "Current plan phase, e.g. access, excavation, material, workshop, room completion.",
            },
            "steps": {
                "type": "array",
                "description": "Ordered short plan steps.",
                "items": {"type": "string"},
                "maxItems": 8,
            },
            "current_step": {"type": "string", "description": "The step to pursue next."},
            "reason": {"type": "string", "description": "Why this plan is appropriate now."},
            "evidence": {
                "type": "string",
                "description": "Evidence from the current screen/state/recent outcomes.",
            },
        },
        "required": ["objective", "steps"],
    },
}

REVIEW_GAMEPLAY_PLAN_TOOL_SPEC: Dict[str, Any] = {
    "name": "review_gameplay_plan",
    "description": (
        "Review the stored gameplay plan against visible state and recent outcomes. "
        "Use this before continuing after stalls or at periodic checkpoints."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "Plan status, e.g. on_track, stalled, needs_revision, milestone_complete.",
            },
            "evidence": {
                "type": "string",
                "description": "Concrete evidence from screen/state/recent action outcomes.",
            },
            "completed_steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Plan steps that now appear complete.",
                "maxItems": 6,
            },
            "blockers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Observed blockers or uncertainty.",
                "maxItems": 6,
            },
            "next_step": {"type": "string", "description": "Next step to execute after the review."},
            "revised_steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional replacement plan steps if the plan needs revision.",
                "maxItems": 8,
            },
            "reason": {"type": "string", "description": "Why the plan should continue or change."},
        },
        "required": ["status", "evidence", "next_step"],
    },
}


RECORD_SCREEN_READ_TOOL_SPEC: Dict[str, Any] = {
    "name": "record_screen_read",
    "description": (
        "Record your own interpretation of the current Dwarf Fortress screen before "
        "submitting keystrokes. This is notebook perception only; it does not act in the game."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "description": (
                    "Current screen or menu mode, e.g. main_map, designation_menu, "
                    "building_menu, workshop_placement, workshop_add_task_list, "
                    "workshop_material_selection, carpenter_workshop_construction_pending, "
                    "manager_orders, manager_new_order_search, manager_required, "
                    "nobles_administrators, stockpile_menu, unknown."
                ),
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Visible screen/status facts supporting this read.",
                "maxItems": 4,
            },
            "cursor_or_selection": {
                "type": "string",
                "description": "What cursor, highlighted item, or active selection appears current.",
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
            },
        },
        "required": ["mode", "evidence", "confidence"],
    },
}


REVIEW_LAST_ACTION_TOOL_SPEC: Dict[str, Any] = {
    "name": "review_last_action",
    "description": (
        "Review whether your previous submitted keystroke action did what you expected. "
        "This is notebook verification only; it does not act in the game."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "worked": {
                "type": ["boolean", "null"],
                "description": "Whether the previous action appears to have worked; null for the first action.",
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Facts comparing the previous expectation to current screen/status/outcome.",
                "maxItems": 4,
            },
            "mismatch_reason": {
                "type": ["string", "null"],
                "description": "Why the previous action failed or diverged, if it did.",
            },
            "should_retry_same_path": {
                "type": "boolean",
                "description": "Whether retrying the same menu/key path is justified by new evidence.",
            },
        },
        "required": ["worked", "evidence", "should_retry_same_path"],
    },
}


class DFWikiTool:
    """Search embedded DF wiki excerpts for gameplay guidance."""

    name = "df_wiki"
    tool_spec = DF_WIKI_TOOL_SPEC

    def __init__(self, docs: Sequence[WikiDoc] | None = None, max_snippets: int = 2) -> None:
        self._docs = list(docs) if docs is not None else list(DEFAULT_DF_WIKI_DOCS)
        self._max_snippets = max(1, max_snippets)
        self._doc_tokens = [
            _tokenize(f"{doc.title} {doc.body} {' '.join(doc.keywords)}")
            for doc in self._docs
        ]

    def query(self, question: str) -> str:
        if not question.strip():
            return "Provide a short question to search the DF wiki notes."
        query_tokens = _tokenize(question)
        if not query_tokens:
            return "Provide a question with keywords about DF mechanics."

        scored: List[tuple[int, WikiDoc]] = []
        for doc, tokens in zip(self._docs, self._doc_tokens):
            score = len(query_tokens & tokens)
            if score:
                scored.append((score, doc))

        if not scored:
            topics = ", ".join(doc.title for doc in self._docs)
            return f"No matching entry found. Topics available: {topics}."

        scored.sort(key=lambda item: item[0], reverse=True)
        snippets = []
        for _, doc in scored[: self._max_snippets]:
            snippet = _excerpt(doc.body, query_tokens, limit=360)
            snippets.append(f"Title: {doc.title}\nExcerpt: {snippet}")
        return "\n\n".join(snippets)


class ToolManager:
    """Load and query agent tools."""

    def __init__(
        self,
        enabled_tools: Sequence[str],
        *,
        memory: MemoryManager | None = None,
    ) -> None:
        self._enabled_tools = list(enabled_tools)
        self._memory = memory
        self.tools = self._load_tools(self._enabled_tools)

    def _load_tools(self, enabled_tools: Sequence[str]) -> Dict[str, DFWikiTool | None]:
        tools: Dict[str, DFWikiTool | None] = {}
        for name in enabled_tools:
            if name == DFWikiTool.name:
                tools[name] = DFWikiTool()
            elif name in {
                "remember_poi",
                "remember_failed_attempt",
                "query_memory",
                "write_gameplay_plan",
                "review_gameplay_plan",
                "record_screen_read",
                "review_last_action",
            }:
                tools[name] = None
            else:
                raise ValueError(f"Unknown tool: {name}")
        return tools

    def tool_specs(self) -> List[Dict[str, Any]]:
        specs: List[Dict[str, Any]] = []
        for name in self._enabled_tools:
            if name == "remember_poi":
                specs.append(REMEMBER_POI_TOOL_SPEC)
            elif name == "remember_failed_attempt":
                specs.append(REMEMBER_FAILED_ATTEMPT_TOOL_SPEC)
            elif name == "query_memory":
                specs.append(QUERY_MEMORY_TOOL_SPEC)
            elif name == "write_gameplay_plan":
                specs.append(WRITE_GAMEPLAY_PLAN_TOOL_SPEC)
            elif name == "review_gameplay_plan":
                specs.append(REVIEW_GAMEPLAY_PLAN_TOOL_SPEC)
            elif name == "record_screen_read":
                specs.append(RECORD_SCREEN_READ_TOOL_SPEC)
            elif name == "review_last_action":
                specs.append(REVIEW_LAST_ACTION_TOOL_SPEC)
            else:
                tool = self.tools.get(name)
                if tool:
                    specs.append(tool.tool_spec)
        return specs

    def handle(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        if tool_name == "remember_poi":
            if self._memory is None:
                return "Memory tool unavailable."
            return self._memory.remember_poi(
                label=str(tool_input.get("label", "")),
                kind=str(tool_input.get("kind", "")),
                x=tool_input.get("x"),
                y=tool_input.get("y"),
                z=tool_input.get("z"),
                status=str(tool_input.get("status", "")),
                evidence=str(tool_input.get("evidence", "")),
            )
        if tool_name == "remember_failed_attempt":
            if self._memory is None:
                return "Memory tool unavailable."
            return self._memory.remember_failed_attempt(
                label=str(tool_input.get("label", "")),
                reason=str(tool_input.get("reason", "")),
                x=tool_input.get("x"),
                y=tool_input.get("y"),
                z=tool_input.get("z"),
                evidence=str(tool_input.get("evidence", "")),
            )
        if tool_name == "query_memory":
            if self._memory is None:
                return "Memory tool unavailable."
            near = tool_input.get("near")
            return self._memory.query_memory(
                query=str(tool_input.get("query", "")),
                kind=str(tool_input.get("kind", "")),
                near=near if isinstance(near, list) else None,
                include_failed=bool(tool_input.get("include_failed", True)),
                limit=int(tool_input.get("limit") or 5),
            )
        if tool_name == "write_gameplay_plan":
            if self._memory is None:
                return "Memory tool unavailable."
            steps = tool_input.get("steps")
            return self._memory.write_gameplay_plan(
                objective=str(tool_input.get("objective", "")),
                phase=str(tool_input.get("phase", "")),
                steps=steps if isinstance(steps, list) else [],
                current_step=str(tool_input.get("current_step", "")),
                reason=str(tool_input.get("reason", "")),
                evidence=str(tool_input.get("evidence", "")),
            )
        if tool_name == "review_gameplay_plan":
            if self._memory is None:
                return "Memory tool unavailable."
            completed_steps = tool_input.get("completed_steps")
            blockers = tool_input.get("blockers")
            revised_steps = tool_input.get("revised_steps")
            return self._memory.review_gameplay_plan(
                status=str(tool_input.get("status", "")),
                evidence=str(tool_input.get("evidence", "")),
                completed_steps=completed_steps if isinstance(completed_steps, list) else [],
                blockers=blockers if isinstance(blockers, list) else [],
                next_step=str(tool_input.get("next_step", "")),
                revised_steps=revised_steps if isinstance(revised_steps, list) else [],
                reason=str(tool_input.get("reason", "")),
            )
        if tool_name == "record_screen_read":
            mode = str(tool_input.get("mode", "")).strip() or "unknown"
            confidence = str(tool_input.get("confidence", "")).strip() or "low"
            return f"Recorded screen read: mode={mode}, confidence={confidence}."
        if tool_name == "review_last_action":
            worked = tool_input.get("worked")
            retry = tool_input.get("should_retry_same_path")
            return (
                "Recorded last-action review: "
                f"worked={worked}, should_retry_same_path={retry}."
            )

        tool = self.tools.get(tool_name)
        if tool is None:
            return f"Unknown tool: {tool_name}"
        question = tool_input.get("question", "")
        if not isinstance(question, str):
            question = str(question)
        return tool.query(question)

    def query(self, tool_name: str, query: str) -> str:
        tool = self.tools.get(tool_name)
        if tool is None:
            return f"Unknown tool: {tool_name}"
        return tool.query(query)


__all__ = [
    "DFWikiTool",
    "ToolManager",
    "WikiDoc",
    "DF_WIKI_TOOL_SPEC",
    "QUERY_MEMORY_TOOL_SPEC",
    "RECORD_SCREEN_READ_TOOL_SPEC",
    "REMEMBER_FAILED_ATTEMPT_TOOL_SPEC",
    "REMEMBER_POI_TOOL_SPEC",
    "REVIEW_GAMEPLAY_PLAN_TOOL_SPEC",
    "REVIEW_LAST_ACTION_TOOL_SPEC",
    "WRITE_GAMEPLAY_PLAN_TOOL_SPEC",
]

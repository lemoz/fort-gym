"""Tooling support for agent tool use."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence


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
    for sentence in sentences:
        if query_tokens & _tokenize(sentence):
            return _truncate(sentence, limit)
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
            "The build menu b lets you place workshops, furnaces, and furniture. "
            "Choose the category and place on clear floor tiles. Most workshops need "
            "materials nearby and a dwarf with the matching labor. Carpenters make "
            "beds and barrels, while masons make stone blocks and furniture. "
            "If placement is blocked, check for walls, ramps, or items on the tile."
        ),
        keywords=("build", "building", "workshop", "furnace", "furniture", "carpenter", "mason"),
    ),
    WikiDoc(
        title="Manager orders and standing orders",
        body=(
            "Manager orders let you queue jobs in bulk. Assign a manager noble, open "
            "the manager screen (j then m), add a new order, choose a job, and set a "
            "quantity or repeat. Standing orders (o) toggle hauling, refuse, and "
            "auto collect. If jobs do not start, check labor assignments and materials."
        ),
        keywords=("manager", "orders", "order", "jobs", "standing", "labor", "materials"),
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

    def __init__(self, enabled_tools: Sequence[str]) -> None:
        self._enabled_tools = list(enabled_tools)
        self.tools = self._load_tools(self._enabled_tools)

    def _load_tools(self, enabled_tools: Sequence[str]) -> Dict[str, DFWikiTool]:
        tools: Dict[str, DFWikiTool] = {}
        for name in enabled_tools:
            if name == DFWikiTool.name:
                tools[name] = DFWikiTool()
            else:
                raise ValueError(f"Unknown tool: {name}")
        return tools

    def tool_specs(self) -> List[Dict[str, Any]]:
        specs: List[Dict[str, Any]] = []
        for name in self._enabled_tools:
            tool = self.tools.get(name)
            if tool:
                specs.append(tool.tool_spec)
        return specs

    def query(self, tool_name: str, query: str) -> str:
        tool = self.tools.get(tool_name)
        if tool is None:
            return f"Unknown tool: {tool_name}"
        return tool.query(query)


__all__ = ["DFWikiTool", "ToolManager", "WikiDoc", "DF_WIKI_TOOL_SPEC"]

"""LLM policy on the DFHack-governed legal action surface.

One OpenRouter decision per step (default ``z-ai/glm-5.2``), submitted through
a single ``submit_action`` tool restricted to DIG/BUILD/ORDER/UNSUSPEND/FARM/LABOR/WAIT/INTERACT.
``MemoryManager`` carries the plan, POIs, and failed attempts across steps.

This module intentionally contains no gameplay heuristics: the model plus the
run loop must solve gameplay. Local logic is limited to transport retry, schema
normalization, and factual review validation. Legacy direct callers can use a
safe WAIT fallback; governed review-controlled runs fail before gameplay when a
bounded retry/correction cannot produce a valid action.
"""

from __future__ import annotations

import json
import os
import re
import time
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import get_settings
from ..env.actions import (
    normalized_action_fingerprint,
    normalized_objective as normalize_objective_identity,
    parse_action,
)
from .base import Agent, register_agent
from .memory import MemoryManager
from .minimap_render import minimap_data_url

GOVERNED_ACTION_TYPES = ("DIG", "BUILD", "ORDER", "UNSUSPEND", "FARM", "LABOR", "WAIT", "INTERACT")
DEFAULT_ADVANCE_TICKS = 1000
MAX_OBJECTIVE_LENGTH = 160

_MEMORY_PATH_ENV_VAR = "FORT_GYM_GOVERNED_MEMORY_PATH"
_MEMORY_PATH_DISABLE_VALUES = {"off", "0"}
_HARD_REVISION_REASON = "same_objective_stalled_2"
_BLOCKED_PROVIDER_FINISH_REASONS = {"content_filter"}
_MINIMAX_M3_MODEL = "minimax/minimax-m3"
_FARM_SEASONS = frozenset({"spring", "summer", "autumn", "winter"})


class GovernedDecisionError(RuntimeError):
    """Fail-closed decision error with a durable terminal classification."""

    terminal_code = "governed_decision_error"

    def __init__(self, message: str, **terminal_details: Any) -> None:
        super().__init__(message)
        self.terminal_details = terminal_details


class GovernedProviderFinishError(GovernedDecisionError):
    """Provider returned a terminal response that cannot contain an action."""

    terminal_code = "provider_content_filter"


class GovernedReviewContractError(GovernedDecisionError):
    """Bounded model corrections could not satisfy the review contract."""

    terminal_code = "governed_review_contract_exhausted"


GOVERNED_SYSTEM_PROMPT = """You are the overseer of a live Dwarf Fortress fortress. You play by issuing \
exactly one bounded, legal overseer command per step, then the real simulation runs and you observe \
what actually changed. You are evaluated only on real observed fortress state, three ways: a scalar \
score paying survival, drink supply, goods actually produced, usable workshops, and created wealth \
(queued orders earn nothing until the goods exist); a rubric judging shelter — enclosed functional \
rooms such as bedrooms and production rooms, fully bounded by walls, buildings, or doors — plus \
production economy, breadth, plan coherence, and non-repetition; and long-horizon goals that value \
building MULTIPLE enclosed functional rooms while keeping every dwarf alive.

Legal actions (the only eight types accepted):
- DIG: params {"area": [x, y, z], "size": [w, h, 1], "kind": "dig"|"channel"|"chop"|"gather"}. \
kind dig designates visible natural WALL tiles; kind channel designates visible natural WALL or \
stable FLOOR tiles. Occupied, constructed, wet, frozen, hidden, tree, and other ineligible tiles \
reject the entire rectangle without changing any tile. Miners must reach an accepted designation \
and work over time. Channel is the legal vertical-access control: channel a visible stable floor \
on the current z-level, then advance time until the native DigChannel job completes. Completion \
opens that tile downward and the observation's Access-level minimap reports the newly visible \
lower z-level and native connectivity. A normal dig aimed directly at a hidden lower z-level \
fails with hidden_unexplored; do not target lower tiles until completed channel access reveals \
them. On an Access-level minimap, only a visible `#` lower-level glyph is a candidate for kind \
dig; `^` is a ramp and a blank is hidden/unreadable. Every tile in a DIG rectangle must qualify, \
so mixing one candidate wall with any ramp or blank rejects the whole rectangle without mutation. \
kind "chop" \
designates the tree trunks inside the rect for felling (the observation's Fort-area tiles line \
reports tree_trunk counts, and the Visible-nearby-trees line reports only the count of visible \
trunks within 40 tiles; choose coordinates from visible map evidence); a dwarf with the \
woodcutting labor fells them over \
time and the logs appear in the Wood stock. Carpentry production consumes wood — without logs, \
workshop orders cancel. kind "gather" designates live shrub tiles inside the rect for plant gathering \
(only live SHRUB-shaped tiles are marked; other tiles in the rect are left untouched and reported as \
non_shrub_tiles); a dwarf with the herbalism labor collects the plant over time and it appears in \
the plant stock. A tile reported as ShrubDead cannot be gathered, cleared by gather, or produce a \
plant; choose a different build footprint instead of retrying it. Verify brewable plant stock or \
completed brew output before treating any gathered plant as brewing input.
- BUILD: params {"kind": "CarpenterWorkshop"|"Still"|"FarmPlot"|"Bed"|"Door"|"Table"|"Chair"|"Wall"|"Floor", \
"x": X, "y": Y, "z": Z, "x2": X2, "y2": Y2 (optional)}. \
CarpenterWorkshop places a 3x3 workshop on open floor within 24 tiles of your fort — near any \
existing building or citizen; choose and verify the complete footprint from observed map facts, \
then a dwarf must construct it. Still places a 3x3 workshop under the same rules. A built Still brews \
plants into drink via ORDER job "brew" — brew orders need brewable plants in stock and empty barrels \
in stock; drink is what dwarves actually consume. \
FarmPlot places a farm plot on open ground: a single tile at (x, y, z), or a rectangle up to 5x5 \
when optional x2/y2 are given, within 24 tiles of your fort; unlike a workshop it consumes no \
material item. Additional FarmPlots also consume no material; acquiring logs does not enable their \
placement. Dwarves with the farming labor plant seasonal crops on them IF seeds are available \
(the embark carries plump helmet spawn); the harvested crops become brewable/cookable plants. The \
z-level alone does not make a plot subterranean: floor directly below an open channel shaft can \
remain light/outside, while excavated floor beneath intact overhead rock is the relevant candidate. \
A one-tile lower-floor FarmPlot is a valid probe. One verified lower-level `.` floor tile is the \
entire minimum footprint, so after connected lower access reveals one, further chamber enlargement \
is not a FarmPlot placement prerequisite. Do not claim that a larger chamber is required unless an \
actual FarmPlot attempt was rejected with a footprint-related error. Choose the target yourself from \
the current lower-level map, advance real work, and use completed plot readback to decide whether \
more excavation is actually needed. \
Only a completed plot's `plot_subterranean=true` and offered-crop readback confirm underground \
farming; `plot_subterranean=false` with empty options cannot grow plump helmets. The \
observation's crew section reports each plot's construction stage. FARM crop selection is durable \
only after that plot reaches its maximum stage; an unfinished plot rejects FARM with \
farm_plot_not_built, so advance real work and observe completion before setting crops. \
Furniture kinds install an already-produced item of that type as a 1x1 building on an unoccupied \
open-floor tile within 24 tiles of your fort — a dwarf hauls and installs it over time; furnishing \
an enclosed space is \
what turns it into a functional room. Installing furniture requires a finished item in \
stock (see "Finished goods in play"); installed beds/doors/tables/chairs make rooms functional. \
Wall and Floor kinds place construction segments: a single tile at (x, y, z), a horizontal or \
vertical line, or a filled rectangle when optional x2/y2 are given, with at most 10 total tiles and \
within 24 tiles of your fort. For a room border use separate one-tile-thick line segments; setting \
both x2 and y2 to different coordinates fills the whole rectangle and does NOT make a room. Each tile consumes one log, \
boulder, or block from stock — and each PENDING construction claims its material immediately, so \
the stocks line's "usable" count is what further BUILDs can actually draw on (locked items free \
up when their job completes or is removed). A room boundary must be a hollow ring around at least \
one untouched passable interior tile; a solid block of W tiles encloses no space. Use one-tile-thick \
border segments and leave the intended interior `.` tiles unbuilt. Enclosed rooms — spaces bounded \
by walls, buildings, or doors — are what make bedrooms and production rooms count; construction \
count alone is not room progress. Only the observation's `enclosed_spaces` and `functional_rooms` \
facts confirm success.
- ORDER: params {"job": <item>, "quantity": 1-5}. Queues production to any BUILT workshop of the \
right kind (construction stage complete), wherever it stands: bed, door, table, chair, barrel, and \
bin need a built Carpenter's Workshop; brew (the brewing reaction) needs a built Still and a \
dwarf with the brewing labor. Dwarves then do the \
work. Created job IDs prove only that DF accepted the command. They do not prove that inputs were \
available, a worker claimed the job, or output was produced. Verify the next observation's matching \
job lifecycle and output counter before attributing output to that order.
- UNSUSPEND: params {"area": [x, y, z], "size": [w, h, 1]} (max 10x10, one z-level). Clears the \
suspended flag on construction/build jobs whose position falls inside the rect. A job suspends \
when a dwarf cannot currently path to or reach the job site or the placement is blocked; the jobs \
observability reports suspended job counts and their positions so you can target the rect precisely. \
This does not complete the job or move any dwarf — it only re-arms the job so a dwarf will \
reattempt it as the simulation continues to run.
- FARM: params {"building_id": <id>, "crop": "<PLANT_TOKEN>"|"clear", "seasons": ["spring","summer","autumn","winter"]}. \
Sets which crop a farm plot grows in each season — the same choice the q-menu crop picker writes. \
A farm plot has four independent season slots (spring, summer, autumn, winter); each holds one \
crop or nothing. crop is a plant raw token (the observation's "Seeds on hand" line lists the \
tokens you hold seeds for, e.g. MUSHROOM_HELMET_PLUMP); "clear" empties the selected seasons. \
seasons is optional — omit it to set all four at once. The observation reports each completed \
underground plot's native offered crops separately for spring, summer, autumn, and winter. Every \
requested season must list the token; otherwise the whole FARM action is rejected with \
crop_not_offered and no slot changes. Surface crop options currently fail closed as \
surface_crop_options_unverified instead of accepting a guessed biome match. \
Setting a crop does not plant it — a dwarf with the farming labor plants a matching seed from \
stock over real time, and only if a seed exists (seeds are consumed by planting; growth then takes \
further time before harvest). Once planting completes, zero active PlantSeeds jobs can mean the \
crop is growing; it is not by itself evidence that the plot is stalled. The observation reports \
each plot's per-season crop tokens, your \
seeds on hand, and the current season. Raw contained-item evidence reports native item fields only; \
it is not a heuristic conclusion about crop growth or route accessibility. Setting a slot to a crop \
it already holds changes nothing.
- LABOR: params {"unit_id": <citizen id>, "labor": <name>, "enable": true|false}. Toggles one \
labor on one citizen, exactly like the player's unit-labors screen. LABOR may target only a \
citizen entry with labor_eligibility_known=true and labor_eligible=true. Never target an entry \
whose eligibility is unknown or false; children and babies remain factual citizens and population \
members but are not labor capacity. A queued job is only ever \
taken by a citizen who has the matching labor enabled: brew jobs need a citizen with brewing, \
farm work needs farming, plant gathering needs herbalism, felling needs woodcutting, mining needs \
mine, wall/floor/workshop construction needs construction, hauling/installing furniture and \
building workshops needs construction, carpentry/masonry/cooking/fishing likewise. Whitelisted \
labor names: mine, woodcutting, carpentry, masonry, farming, herbalism, brewing, fishing, \
construction, cooking. Enabling a labor lets that citizen pick up a matching starved job; it \
completes no work itself and moves no dwarf — a dwarf must still path to and perform the job over \
time. The bounded Citizens line lists each displayed citizen id with attested labor and current-job \
state. labors_known=false or current_job_known=false is unknown evidence, not disabled labor or \
idleness. list_truncated=true means additional citizens are not displayed; target only a displayed \
entry with the required true eligibility fields and never infer eligibility for a hidden citizen.
- WAIT: params {}. Issues nothing and lets the simulation run.
- INTERACT: params {"operation": "confirm"|"cancel"|"up"|"down"|"left"|"right"|"finish_topic_meeting"|"topic_option_a"|...|"topic_option_h"}. Sends exactly one
semantic input to a paused interface or dialog, then observes one screen after that input. It must
use advance_ticks=0 and never advances simulation time. Use it only when the observation says the
game is PAUSED and reports an interactive DF Viewscreen; the runner rejects all other contexts.
Use finish_topic_meeting only on viewscreen_topicmeetingst when the visible option says
"a - Finish peeking in on conversation"; it sends exactly that one bounded letter option. Use a
topic_option_a through topic_option_h operation only when that exact lettered option is visibly
listed on viewscreen_topicmeetingst; each sends one corresponding bounded letter option. In
particular, "a - Begin discussion" requires topic_option_a and must never use
finish_topic_meeting.
`viewscreen_storesst` is a blocking Wealth/Stocks screen: submit only INTERACT cancel with
advance_ticks=0, then wait for a fresh observation before any gameplay command or time advancement.

Every action must include "advance_ticks" (how many game ticks to run after the command, up to \
the declared submit_action maximum; around 1000 is a typical step; INTERACT must use 0). Nothing in the fortress changes unless
time advances.

The observation includes a Fort minimap — a top-down character grid (and, when attached, the \
same grid rendered as a color image) of your fort area with a \
coordinate ruler (W=your walls, x=your queued wall/floor a dwarf is still building — never \
re-place on an x tile, advance time instead, b/t/c/d=furniture, w=workshop, o=other occupied \
building footprint, .=stable open floor, ,=gatherable shrub, s=sapling, p=loose rock, \
i=frozen liquid that can thaw). It is the \
authoritative view for BUILD placement and wall geometry. Before submitting any BUILD, derive its \
full target footprint and verify every target tile is `.` open floor in the current minimap. Never \
BUILD on `W`, `#`, `T`, `b`, `t`, `c`, `d`, `w`, `o`, `x`, `i`, `,`, `s`, `p`, `@`, or `~`, a coordinate \
listed under Furniture positions, or a \
coordinate just reported under Failed tiles. If the footprint is not provably open and unoccupied, \
choose a different valid tile or a different productive action; WAIT only when advancing the \
simulation can change the relevant world state, and name the change you expect. Do not retry a \
rejected target until an observed fact about that tile changes. An enclosure must form a complete \
hollow ring with floor \
inside; trace it on the minimap and wall the gaps. It also gives the recorded game screen text \
plus plan-agnostic work and crew facts: active jobs, workshop counts and usability, citizen \
positions/labors, and manager order counts. Read them to see whether \
your previous command actually worked before issuing the next one. A == MEMORY == section carries \
your own plan, POIs, and failed attempts from earlier steps. For DIG and BUILD, cross-check every \
coordinate named in intent, plan_step, or expected_simulation_result against params before submission; \
the params are the real control and must target the tile you describe.

The Run resource flow lines are factual counters from DF item-creation events and each citizen's
eat/drink history since this run began. Use them to verify that farming and brewing
are out-producing consumption; current stock totals alone do not prove a sustainable loop.
The G7 planning facts line compares those counters and other ratified thresholds without choosing a
strategy for you. A branch marked `below`, or a count below its shown requirement, remains
unresolved; `unknown` is not success. Never describe either as complete or sustainable until the
observed facts meet the stated condition. At plan review, account honestly for every unresolved
branch even when you choose to work on a different one this turn. This planning line is not the
terminal G7 verdict: evidence integrity, run scope, rubric, and scalar score are evaluated later.
The death branch says `no_neglect_observed` only when its run-scoped evidence is complete and either
no dwarf died or every recorded death has a known cause with zero neglect deaths. `unknown` remains
unresolved, and `neglect_observed` is direct evidence that the branch is not clear.

Dwarves and jobs run in parallel. An active specialist job occupies its assigned dwarf; an
unassigned queued job occupies nobody. Any legal action with positive advance_ticks lets all existing
jobs progress. Adding another copy creates a distinct job; it does not make an existing job finish or
verify that the earlier command worked.

A Jobs sample can report `target_walk_group_connectivity=connected|disconnected|unknown` for its
target tile. `connected` means the cached native check says at least one current citizen may share a
walk group with the target; `disconnected` means every checked citizen is in a different cached walk
group; `unknown` is not evidence of either. This is geometry only, not a current path guarantee: it
does not account for unit-specific restrictions or prove that a citizen has the needed labor, will
claim the job, or can obtain required materials.

The observation's AGENT PLAN CONTROL lines are a policy-neutral review checkpoint. They state the
exact previous step and factual verdict, whether a plan review is due, its request_id, and the prior
objective. You choose the objective and gameplay actions. The harness only checks that your review
matches those facts and cites evidence grounded in the runner-authored factual allowlist. Cite the
AGENT PLAN CONTROL previous-attempt line for last_action_review and current state lines for the
plan. Submit only the `E#` ids shown in REVIEW EVIDENCE CHOICES; do not submit excerpts or use
model-authored action history or Last Action command/detail as evidence.

Review the previous command against its declared expected simulation result. Command acceptance is
not action success. A concurrent wall, workshop, stock, or score change during the same tick window
does not prove an ORDER, FARM, BUILD, or other command caused its intended effect. For ORDER, use
the action-specific lifecycle plus the matching produced-goods or drink-production counter. A
pending job is partial, and a created job that vanished without matching output is no progress.

At every due plan review, compare all of the factual branches rather than defending the current
queue: resource production versus consumption, enclosed and functional rooms, built production
facilities, run-scoped death evidence, idle citizens and their labors, queued/active/suspended jobs,
and recent rejected or no-progress targets. Record pending actions as pending, and
classify a coordinate or footprint as
stalled when two reviews show no progress and no observed job can change it. Choose the next
objective and action yourself from those facts.

When AGENT PLAN CONTROL reasons includes exactly `same_objective_stalled_2`, two rejected or
no-progress attempts are not progress and decision=continue is invalid. You must use
decision=revise, keep prior_objective as the stalled objective, choose a genuinely different current
objective, and submit an action that advances that replacement objective. The action's normalized
type and params must differ from the previous rejected or no-progress action even when
retry_same_action=true. Merely renaming the stalled objective or choosing another target for the
same rejected approach is not a revision. The harness identifies the stall but does not choose the
replacement objective or action. This hard transition applies only to
`same_objective_stalled_2`; do not infer it from `periodic`, `partial_mutation`, or `action_pending`
review reasons.

With each action also submit:
- "intent": one sentence on what this command does.
- "objective": the short, durable fortress goal this action advances (used as your persistent plan
  objective; keep it under 160 characters and do not include changing counts, evidence IDs, step
  numbers, or other volatile observation facts — put those details in intent or plan_step).
- "plan_step": which step of your plan this is.
- "expected_simulation_result": what the real simulation should show afterwards if it worked.
- "last_action_review": previous_step and verdict exactly matching AGENT PLAN CONTROL, one or more
  factual evidence ids, retry_same_action, and a short lesson. Copy the id after
  "Required last_action_review.evidence id:" exactly as one evidence item. retry_same_action
  must be true exactly when this action repeats the previous action's normalized type and params.
  Use step -1 and verdict unknown only when there is no previous action attempt.
- "plan_review": request_id from AGENT PLAN CONTROL, decision
  not_due|establish|continue|revise|complete, prior_objective, objective, at least two distinct
  factual evidence ids, and reason. When observed facts meet the current objective's stated
  measurable condition, you must use decision=complete rather than continue: prior_objective
  remains the completed objective, objective becomes a genuinely different next objective, and the
  submitted action advances only that next objective. `complete` records a local objective
  transition; it is not terminal G7 completion. A complete review must cite at least one non-control
  current game-state evidence id even when review_due=no. When review_due=yes, establish the first
  plan, continue the exact prior objective, revise to a genuinely different objective, or complete
  the prior objective as above. When review_due=no, use not_due unless you voluntarily
  continue/review, revise, or complete the objective. Any objective change, including when
  review_due=no, requires decision=revise or decision=complete; otherwise copy the prior objective
  exactly without paraphrasing it. `reason` may be omitted only for decision=not_due.
  plan_review.objective must equal objective; the top-level plan_step is the next plan step.
- "memory_update" (optional): a fact worth remembering, as "label @ x,y,z: note" if it has a \
location.

Be honest: if the metrics show your last action did nothing, say so in your next intent and adapt. \
Repeating an identical failing action wastes the run and is scored against you."""


def _submit_action_tool(*, max_advance_ticks: int = 2000) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "submit_action",
            "description": "Submit exactly one legal governed fortress action.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": list(GOVERNED_ACTION_TYPES)},
                    "params": {"type": "object"},
                    "intent": {"type": "string"},
                    "objective": {
                        "type": "string",
                        "maxLength": MAX_OBJECTIVE_LENGTH,
                        "description": (
                            "Short durable fortress goal; omit live counts, evidence IDs, and "
                            "step numbers."
                        ),
                    },
                    "plan_step": {"type": "string"},
                    "expected_simulation_result": {"type": "string"},
                    "last_action_review": {
                        "type": "object",
                        "properties": {
                            "previous_step": {"type": "integer", "minimum": -1},
                            "verdict": {
                                "type": "string",
                                "enum": [
                                    "progressed",
                                    "partial",
                                    "rejected",
                                    "no_progress",
                                    "unknown",
                                ],
                            },
                            "evidence": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                                "maxItems": 4,
                            },
                            "retry_same_action": {"type": "boolean"},
                            "lesson": {"type": "string"},
                        },
                        "required": [
                            "previous_step",
                            "verdict",
                            "evidence",
                            "retry_same_action",
                            "lesson",
                        ],
                        "additionalProperties": False,
                    },
                    "plan_review": {
                        "type": "object",
                        "properties": {
                            "request_id": {"type": "string"},
                            "decision": {
                                "type": "string",
                                "enum": [
                                    "not_due",
                                    "establish",
                                    "continue",
                                    "revise",
                                    "complete",
                                ],
                            },
                            "prior_objective": {"type": "string"},
                            "objective": {
                                "type": "string",
                                "maxLength": MAX_OBJECTIVE_LENGTH,
                            },
                            "evidence": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 2,
                                "maxItems": 4,
                            },
                            "reason": {"type": "string"},
                            "steps": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 8,
                            },
                        },
                        "required": [
                            "request_id",
                            "decision",
                            "prior_objective",
                            "objective",
                            "evidence",
                        ],
                        "additionalProperties": False,
                    },
                    "memory_update": {"type": "string"},
                    "advance_ticks": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": max_advance_ticks,
                        "description": "Game ticks to run after the command (~1000 typical).",
                    },
                },
                "required": [
                    "type",
                    "params",
                    "intent",
                    "objective",
                    "plan_step",
                    "expected_simulation_result",
                    "last_action_review",
                    "plan_review",
                    "advance_ticks",
                ],
            },
        },
    }


_GLM52_JSON_TRANSPORT_INSTRUCTION = (
    "Transport requirement: return exactly one JSON object for submit_action, without Markdown. "
    "Include every required top-level field: type, params, intent, objective, plan_step, "
    "expected_simulation_result, last_action_review, plan_review, and advance_ticks. "
    "Use JSON objects for last_action_review and plan_review, and a JSON string for plan_step. "
    "The governed validator rejects missing, mistyped, or factually inconsistent fields before "
    "gameplay."
)


_LAST_ACTION_LINE = re.compile(r"^Last Action:.*$", re.MULTILINE)
_MEMORY_UPDATE_POI = re.compile(
    r"^(?P<label>[^@]{1,80})@\s*(?P<x>-?\d+)\s*,\s*(?P<y>-?\d+)\s*,\s*(?P<z>-?\d+)\s*:?\s*(?P<note>.*)$"
)

GOVERNED_OBSERVATION_PREAMBLE = (
    "The next user message is the current live Dwarf Fortress observation. "
    "Treat it as authoritative, inspect any attached minimap, and submit exactly one legal action."
)


class DFHackGovernedLLMAgent(Agent):
    """OpenRouter policy for the eight-action governed DFHack gameplay surface.

    ``memory_path`` controls disk persistence of POIs, failed attempts, plan,
    and summary across runs (runs on the same seed save share the same map,
    so this state stays valid run to run). ``"auto"`` (the default) resolves
    a path from ``FORT_GYM_GOVERNED_MEMORY_PATH`` (set to ``"off"``/``"0"``
    to disable) or falls back to ``<ARTIFACTS_DIR>/governed_llm_memory.json``.
    Pass ``None`` to disable persistence entirely, or an explicit path string.
    """

    def __init__(
        self,
        *,
        model_override: str | None = None,
        api_key: str | None = None,
        max_attempts: int | None = None,
        memory_path: str | None = "auto",
        vision: bool = False,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
        prompt_cache: str | None = None,
        omit_temperature: bool = False,
        memory_window: int | None = None,
        max_advance_ticks: int = 2000,
    ) -> None:
        self._vision = vision
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort
        self._prompt_cache = prompt_cache
        self._omit_temperature = omit_temperature
        self._session_id: str | None = None
        self._max_advance_ticks = max_advance_ticks
        self._settings = get_settings()
        self._api_key = api_key if api_key is not None else self._settings.OPENROUTER_API_KEY
        if not self._api_key:
            raise RuntimeError("OPENROUTER_API_KEY not configured")
        self._model = model_override or self._settings.OPENROUTER_MODEL
        self._max_attempts = (
            self._settings.OPENROUTER_MAX_ATTEMPTS if max_attempts is None else max_attempts
        )
        self._client = None
        self._last_call = 0.0
        self._memory = MemoryManager(
            window_size=(
                self._settings.MEMORY_WINDOW if memory_window is None else memory_window
            )
        )
        self._tool_events: List[Dict[str, Any]] = []
        self._pending: Optional[Dict[str, Any]] = None
        self._memory_path = self._resolve_memory_path(memory_path)
        self._load_memory()

    def set_run_context(self, *, run_id: str) -> None:
        """Keep OpenRouter routing and cache affinity stable within one run."""
        self._session_id = f"fort-gym:{run_id}"

    # -- memory persistence ------------------------------------------------

    def _resolve_memory_path(self, memory_path: str | None) -> Path | None:
        if memory_path is None:
            return None
        if memory_path != "auto":
            return Path(memory_path)
        env_value = os.getenv(_MEMORY_PATH_ENV_VAR)
        if env_value is not None and env_value.strip():
            if env_value.strip().lower() in _MEMORY_PATH_DISABLE_VALUES:
                return None
            return Path(env_value.strip())
        return Path(self._settings.ARTIFACTS_DIR) / "governed_llm_memory.json"

    def _load_memory(self) -> None:
        if self._memory_path is None:
            return
        try:
            if not self._memory_path.is_file():
                return
            data = json.loads(self._memory_path.read_text(encoding="utf-8"))
            self._memory.load_dict(data if isinstance(data, dict) else {})
        except Exception as exc:
            self._tool_events.append(
                {
                    "tool": "governed_llm.load_memory",
                    "input": {"path": str(self._memory_path)},
                    "output": {"error": type(exc).__name__, "message": str(exc)},
                }
            )

    def _save_memory(self) -> None:
        if self._memory_path is None:
            return
        try:
            self._memory_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._memory_path.with_name(self._memory_path.name + ".tmp")
            tmp_path.write_text(json.dumps(self._memory.to_dict()), encoding="utf-8")
            os.replace(tmp_path, self._memory_path)
        except Exception as exc:
            self._tool_events.append(
                {
                    "tool": "governed_llm.save_memory",
                    "input": {"path": str(self._memory_path)},
                    "output": {"error": type(exc).__name__, "message": str(exc)},
                }
            )

    # -- transport -------------------------------------------------------

    def _client_instance(self):
        if self._client is None:
            try:
                openai_mod = import_module("openai")
            except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
                raise RuntimeError("openai package not installed") from exc
            client_cls = getattr(openai_mod, "OpenAI", None)
            if client_cls is None:
                raise RuntimeError("openai.OpenAI client not available")
            self._client = client_cls(
                api_key=self._api_key,
                base_url=self._settings.OPENROUTER_BASE_URL,
                max_retries=0,
                timeout=self._settings.OPENROUTER_TIMEOUT_SECONDS,
            )
        return self._client

    def _rate_limit(self) -> None:
        limit = self._settings.LLM_RATE_LIMIT_TPS
        if limit <= 0:
            return
        interval = 1.0 / limit
        wait = interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _create_completion(self, messages: List[Dict[str, Any]]) -> Any:
        request_messages = [dict(message) for message in messages]
        if self._prompt_cache == "explicit_ephemeral" and request_messages:
            system = request_messages[0]
            if system.get("role") == "system" and isinstance(system.get("content"), str):
                system["content"] = [
                    {
                        "type": "text",
                        "text": system["content"],
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
        if self._model == "z-ai/glm-5.2":
            # Exact-state probes were 3/3 valid in JSON mode; both forced and
            # auto tool transports repeatedly returned partial argument objects.
            request_kwargs: Dict[str, Any] = {"response_format": {"type": "json_object"}}
            request_messages = [
                *messages,
                {"role": "user", "content": _GLM52_JSON_TRANSPORT_INSTRUCTION},
            ]
        else:
            request_kwargs = {
                "tools": [_submit_action_tool(max_advance_ticks=self._max_advance_ticks)],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": "submit_action"},
                },
            }
        extra_body: Dict[str, Any] = {}
        if self._reasoning_effort:
            extra_body["reasoning"] = {
                "effort": self._reasoning_effort,
                "exclude": True,
            }
        elif self._settings.OPENROUTER_DISABLE_REASONING:
            extra_body["reasoning"] = {"enabled": False, "exclude": True}
        if self._session_id:
            extra_body["session_id"] = self._session_id
            if self._prompt_cache == "automatic":
                extra_body["prompt_cache_key"] = self._session_id
        if extra_body:
            request_kwargs["extra_body"] = extra_body
        completion_kwargs: Dict[str, Any] = {
            "model": self._model,
            "messages": request_messages,
            "max_tokens": self._max_tokens or self._settings.LLM_MAX_TOKENS,
            **request_kwargs,
        }
        if not self._omit_temperature:
            completion_kwargs["temperature"] = self._settings.LLM_TEMP
        max_attempts = max(1, self._max_attempts)
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                self._rate_limit()
                response = self._client_instance().chat.completions.create(
                    **completion_kwargs
                )
                return self._reject_blocked_provider_finish(response)
            except GovernedProviderFinishError as exc:
                last_exc = exc
                will_retry = attempt + 1 < max_attempts
                self._tool_events.append(
                    {
                        "tool": "governed_llm.provider_finish_retry",
                        "input": {"model": self._model, "attempt": attempt + 1},
                        "output": {
                            **exc.terminal_details,
                            "retrying": will_retry,
                        },
                    }
                )
                if will_retry:
                    time.sleep(min(2.0 * (attempt + 1), 5.0))
            except Exception as exc:
                # some providers (e.g. Kimi K2.7) refuse to run with reasoning
                # disabled; drop the disable flag once and retry immediately
                if (
                    "reasoning is mandatory" in str(exc).lower()
                    and self._reasoning_effort is None
                    and "extra_body" in completion_kwargs
                ):
                    degraded_extra = dict(completion_kwargs.get("extra_body") or {})
                    degraded_extra.pop("reasoning", None)
                    if degraded_extra:
                        completion_kwargs["extra_body"] = degraded_extra
                    else:
                        completion_kwargs.pop("extra_body", None)
                    self._tool_events.append(
                        {
                            "tool": "governed_llm.reasoning_enabled_degraded",
                            "input": {"model": self._model},
                            "output": {"reasoning_disable_dropped": True},
                        }
                    )
                    try:
                        self._rate_limit()
                        response = self._client_instance().chat.completions.create(
                            **completion_kwargs
                        )
                        return self._reject_blocked_provider_finish(response)
                    except Exception as retry_exc:
                        exc = retry_exc
                # some providers (e.g. Z.AI vision endpoints) reject forced
                # tool_choice; degrade to auto once and retry immediately
                if (
                    "tool choice" in str(exc).lower()
                    and "tools" in completion_kwargs
                    and completion_kwargs.get("tool_choice") != "auto"
                ):
                    completion_kwargs["tool_choice"] = "auto"
                    self._tool_events.append(
                        {
                            "tool": "governed_llm.tool_choice_degraded",
                            "input": {"model": self._model},
                            "output": {"tool_choice": "auto"},
                        }
                    )
                    try:
                        self._rate_limit()
                        response = self._client_instance().chat.completions.create(
                            **completion_kwargs
                        )
                        return self._reject_blocked_provider_finish(response)
                    except Exception as retry_exc:
                        exc = retry_exc
                last_exc = exc
                will_retry = attempt + 1 < max_attempts
                self._tool_events.append(
                    {
                        "tool": "openrouter.chat.completions.create",
                        "input": {"model": self._model, "attempt": attempt + 1},
                        "output": {
                            "error": type(exc).__name__,
                            "message": str(exc),
                            "retrying": will_retry,
                        },
                    }
                )
                if will_retry:
                    time.sleep(min(2.0 * (attempt + 1), 5.0))
        if isinstance(last_exc, GovernedProviderFinishError):
            last_exc.terminal_details["attempts"] = max_attempts
            raise last_exc
        raise RuntimeError(f"openrouter request failed after {max_attempts} attempts") from last_exc

    def _reject_blocked_provider_finish(self, response: Any) -> Any:
        choices = list(self._field(response, "choices") or [])
        finish_reasons = [
            str(reason)
            for reason in (
                self._field(choice, "finish_reason") for choice in choices
            )
            if reason is not None
        ]
        blocked = sorted(
            {
                reason.lower()
                for reason in finish_reasons
                if reason.lower() in _BLOCKED_PROVIDER_FINISH_REASONS
            }
        )
        if not blocked:
            return response

        self._record_response_telemetry(response, choices)
        generation_id = self._field(response, "id")
        raise GovernedProviderFinishError(
            "provider blocked the governed action response: " + ", ".join(blocked),
            finish_reasons=finish_reasons,
            generation_id=generation_id,
        )

    # -- memory ----------------------------------------------------------

    def _record_previous_outcome(self, obs_text: str) -> None:
        if self._pending is None:
            return
        match = _LAST_ACTION_LINE.search(obs_text or "")
        result = match.group(0) if match else ""
        self._memory.add_step(
            observation=self._pending.get("observation_digest", ""),
            action=self._pending.get("action", {}),
            result=result,
        )
        if result and "REJECTED" in result.upper():
            action = self._pending.get("action", {})
            params = action.get("params") if isinstance(action.get("params"), dict) else {}
            label_parts = [str(action.get("type", "unknown"))]
            kind = params.get("kind") or params.get("job")
            if kind:
                label_parts.append(str(kind))
            if params.get("x") is not None and params.get("y") is not None:
                label_parts.append(f"at ({params.get('x')},{params.get('y')})")
            elif isinstance(params.get("area"), (list, tuple)):
                area = params.get("area")
                label_parts.append(f"at ({area[0]},{area[1]})")
            self._memory.remember_failed_attempt(
                label=" ".join(label_parts) + " rejected",
                reason=result,
            )
        self._pending = None

    def _apply_memory_fields(self, action: Dict[str, Any]) -> None:
        objective = str(action.get("objective") or "").strip()
        plan_review = action.get("plan_review")
        if isinstance(plan_review, dict):
            decision = str(plan_review.get("decision") or "")
            evidence = " | ".join(str(item) for item in plan_review.get("evidence") or [])
            next_step = str(action.get("plan_step") or "").strip()
            if decision in {"establish", "revise", "complete"}:
                self._memory.write_gameplay_plan(
                    objective=objective,
                    steps=plan_review.get("steps") or [],
                    current_step=next_step,
                    reason=str(plan_review.get("reason") or ""),
                    evidence=evidence,
                )
            elif decision == "continue" and self._memory.gameplay_plan:
                self._memory.review_gameplay_plan(
                    status="continue",
                    evidence=evidence,
                    next_step=next_step,
                    reason=str(plan_review.get("reason") or ""),
                )
            elif decision == "not_due" and self._memory.gameplay_plan:
                self._memory.gameplay_plan = {
                    **self._memory.gameplay_plan,
                    "current_step": next_step[:120],
                }
        elif objective:
            # Backward-compatible path for direct callers without plan control.
            self._memory.write_gameplay_plan(
                objective=objective,
                current_step=str(action.get("plan_step") or "").strip(),
            )
        update = str(action.get("memory_update") or "").strip()
        if update:
            poi = _MEMORY_UPDATE_POI.match(update)
            if poi:
                self._memory.remember_poi(
                    label=poi.group("label").strip(),
                    x=poi.group("x"),
                    y=poi.group("y"),
                    z=poi.group("z"),
                    evidence=poi.group("note").strip(),
                )
            else:
                self._memory.remember_poi(label=update)

    # -- action handling ---------------------------------------------------

    @staticmethod
    def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(payload)
        normalized["type"] = str(normalized.get("type") or "").strip().upper()
        params = normalized.get("params")
        normalized["params"] = dict(params) if isinstance(params, dict) else {}
        if normalized.get("type") == "ORDER":
            order = normalized["params"]
            if "quantity" not in order and "qty" in order:
                order["quantity"] = order.pop("qty")
        if "advance_ticks" not in normalized and normalized.get("type") != "INTERACT":
            normalized["advance_ticks"] = DEFAULT_ADVANCE_TICKS
        return normalized

    @staticmethod
    def _wrapped_coordinate_triplet(value: Any) -> list[int] | None:
        """Decode one observed provider wrapper without weakening validation."""

        if not isinstance(value, dict) or set(value) != {"item"}:
            return None
        raw_items = value.get("item")
        if not isinstance(raw_items, list) or len(raw_items) != 3:
            return None
        coordinates: list[int] = []
        for raw in raw_items:
            if type(raw) is int:
                coordinates.append(raw)
                continue
            if isinstance(raw, str) and re.fullmatch(r"-?\d+", raw.strip()):
                coordinates.append(int(raw.strip()))
                continue
            return None
        return coordinates

    def _normalize_provider_coordinate_wrappers(
        self, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Normalize MiniMax's exact ``{"item": [x, y, z]}`` transport quirk."""

        action_type = str(payload.get("type") or "").strip().upper()
        coordinate_fields = {
            "DIG": ("area", "size"),
            "UNSUSPEND": ("area", "size"),
            "BUILD": ("location",),
        }.get(action_type, ())
        params = payload.get("params")
        if not coordinate_fields or not isinstance(params, dict):
            return payload

        normalized_params = dict(params)
        normalized_fields: list[str] = []
        for field in coordinate_fields:
            coordinates = self._wrapped_coordinate_triplet(params.get(field))
            if coordinates is None:
                continue
            normalized_params[field] = coordinates
            normalized_fields.append(field)
        if not normalized_fields:
            return payload

        normalized = dict(payload)
        normalized["params"] = normalized_params
        self._tool_events.append(
            {
                "tool": "governed_llm.coordinate_wrapper_normalized",
                "input": {"action_type": action_type},
                "output": {"fields": normalized_fields},
            }
        )
        return normalized

    @staticmethod
    def _wrapped_farm_seasons(value: Any) -> list[str] | None:
        """Decode MiniMax's exact season-list wrapper without coercion."""

        if not isinstance(value, dict) or set(value) != {"item"}:
            return None
        raw_items = value.get("item")
        if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 4:
            return None
        if any(type(item) is not str or item not in _FARM_SEASONS for item in raw_items):
            return None
        if len(set(raw_items)) != len(raw_items):
            return None
        return list(raw_items)

    def _normalize_minimax_farm_seasons_wrapper(
        self, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Repair one observed MiniMax FARM transport shape, fail-closed."""

        if self._model != _MINIMAX_M3_MODEL:
            return payload
        action_type = str(payload.get("type") or "").strip().upper()
        params = payload.get("params")
        if action_type != "FARM" or not isinstance(params, dict):
            return payload
        seasons = self._wrapped_farm_seasons(params.get("seasons"))
        if seasons is None:
            return payload

        normalized = dict(payload)
        normalized["params"] = {**params, "seasons": seasons}
        self._tool_events.append(
            {
                "tool": "governed_llm.farm_seasons_wrapper_normalized",
                "input": {
                    "action_type": action_type,
                    "field": "seasons",
                    "wrapper": "item",
                },
                "output": {"item_count": len(seasons)},
            }
        )
        return normalized

    def _normalize_duplicated_objective_length(
        self, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Bound identical duplicated objective prose at the schema boundary."""

        objective = payload.get("objective")
        plan_review = payload.get("plan_review")
        if not isinstance(objective, str) or not isinstance(plan_review, dict):
            return payload
        plan_objective = plan_review.get("objective")
        if not isinstance(plan_objective, str):
            return payload

        stripped = objective.strip()
        if (
            stripped != plan_objective.strip()
            or len(stripped) <= MAX_OBJECTIVE_LENGTH
            or "\n" in stripped
            or "\r" in stripped
        ):
            return payload

        shortened = stripped[:MAX_OBJECTIVE_LENGTH]
        word_boundary = shortened.rfind(" ")
        if word_boundary > 0:
            shortened = shortened[:word_boundary]

        normalized = dict(payload)
        normalized_plan_review = dict(plan_review)
        normalized["objective"] = shortened
        normalized_plan_review["objective"] = shortened
        normalized["plan_review"] = normalized_plan_review
        self._tool_events.append(
            {
                "tool": "governed_llm.objective_length_normalized",
                "input": {},
                "output": {
                    "original_length": len(stripped),
                    "normalized_length": len(shortened),
                },
            }
        )
        return normalized

    def _normalize_objective_quote_artifacts(
        self, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Repair one corroborated terminal quote across duplicated objectives."""

        plan_review = payload.get("plan_review")
        if not isinstance(plan_review, dict):
            return payload

        objective = payload.get("objective")
        plan_objective = plan_review.get("objective")
        if not isinstance(objective, str) or not isinstance(plan_objective, str):
            return payload

        def without_lone_terminal_quote(value: str) -> str | None:
            stripped = value.strip()
            if (
                stripped.endswith('"')
                and stripped.count('"') % 2 == 1
                and stripped[:-1].strip()
            ):
                return stripped[:-1].rstrip()
            return None

        cleaned_objective = without_lone_terminal_quote(objective)
        cleaned_plan_objective = without_lone_terminal_quote(plan_objective)
        if (cleaned_objective is None) == (cleaned_plan_objective is None):
            return payload

        if cleaned_objective is not None:
            if cleaned_objective != plan_objective.strip():
                return payload
            canonical = plan_objective.strip()
            changed_field = "objective"
        else:
            assert cleaned_plan_objective is not None
            if cleaned_plan_objective != objective.strip():
                return payload
            canonical = objective.strip()
            changed_field = "plan_review.objective"

        normalized = dict(payload)
        normalized_plan_review = dict(plan_review)
        normalized["objective"] = canonical
        normalized_plan_review["objective"] = canonical
        normalized["plan_review"] = normalized_plan_review
        self._tool_events.append(
            {
                "tool": "governed_llm.objective_quote_artifact_normalized",
                "input": {},
                "output": {"fields": [changed_field]},
            }
        )
        return normalized

    def _normalize_redundant_plan_decision(
        self, payload: Dict[str, Any], control: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Canonicalize ``revise`` when the submitted objective did not change."""

        if self._requires_hard_revision(control):
            return payload
        plan_review = payload.get("plan_review")
        if not isinstance(plan_review, dict) or plan_review.get("decision") != "revise":
            return payload
        prior_objective = self._normalized_prior_objective(control.get("prior_objective"))
        if not prior_objective:
            return payload
        if self._normalized_objective(payload.get("objective")) != prior_objective:
            return payload

        canonical_decision = "continue" if bool(control.get("review_due")) else "not_due"
        normalized = dict(payload)
        normalized_plan_review = dict(plan_review)
        normalized_plan_review["decision"] = canonical_decision
        normalized["plan_review"] = normalized_plan_review
        self._tool_events.append(
            {
                "tool": "governed_llm.plan_decision_normalized",
                "input": {"request_id": control.get("request_id")},
                "output": {
                    "original_decision": "revise",
                    "normalized_decision": canonical_decision,
                    "reason": "submitted_objective_matches_prior",
                },
            }
        )
        return normalized

    def _fallback_wait(self, reason: str) -> Dict[str, Any]:
        self._tool_events.append(
            {"tool": "governed_llm.fallback_wait", "input": {}, "output": {"reason": reason}}
        )
        self._memory.remember_failed_attempt(label="llm step fallback", reason=reason[:180])
        return parse_action(
            {
                "type": "WAIT",
                "params": {},
                "intent": f"fallback wait: {reason[:140]}",
                "objective": "Keep the simulation advancing despite a failed policy step.",
                "expected_simulation_result": "Existing jobs progress while the policy recovers.",
                "advance_ticks": DEFAULT_ADVANCE_TICKS,
            }
        )

    @staticmethod
    def _normalized_objective(value: Any) -> str:
        return normalize_objective_identity(value)

    @classmethod
    def _normalized_prior_objective(cls, value: Any) -> str:
        normalized = cls._normalized_objective(value)
        return "" if normalized in {"none", "null", "n/a", "no prior objective"} else normalized

    @staticmethod
    def _requires_hard_revision(control: Dict[str, Any]) -> bool:
        reasons = control.get("reasons")
        return isinstance(reasons, list) and _HARD_REVISION_REASON in reasons

    @staticmethod
    def _decision_satisfies_requirement(decision: Any, requirement: str) -> bool:
        if requirement == "not_due or continue":
            return decision in {"not_due", "continue"}
        return decision == requirement

    @staticmethod
    def _matching_evidence_line(quote: str, obs_text: str) -> str | None:
        evidence_id = quote.strip()
        if re.fullmatch(r"E\d+", evidence_id) is None:
            return None
        for line in obs_text.splitlines():
            if line.startswith(evidence_id + ": "):
                return line
        return None

    @classmethod
    def _evidence_error(cls, value: Any, obs_text: str, field: str) -> str | None:
        if not isinstance(value, list) or not value:
            return f"{field} must contain at least one allowed evidence id (E#)"
        for quote in value:
            if not isinstance(quote, str) or not quote.strip():
                return f"{field} contains an empty or non-string evidence id"
            if "\n" in quote or "\r" in quote:
                return f"{field} evidence ids must be single-line"
            if cls._matching_evidence_line(quote, obs_text) is None:
                return f"{field} contains an unknown evidence id: {quote!r}"
        return None

    @staticmethod
    def _scalar_contract_error(
        value: Any,
        field: str,
        *,
        max_length: int | None = None,
    ) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return f"{field} is required by the governed review contract"
        if "\n" in value or "\r" in value:
            return f"{field} must be single-line"
        if max_length is not None and len(value.strip()) > max_length:
            return f"{field} must be at most {max_length} characters"
        return None

    def _review_contract_errors(
        self,
        payload: Dict[str, Any],
        obs_text: str,
        control: Dict[str, Any],
        fingerprint_action: Dict[str, Any] | None,
    ) -> List[str]:
        errors: List[str] = []
        repeats_previous_action: bool | None = None
        allowed_evidence_lines = control.get("allowed_evidence_lines")
        if not isinstance(allowed_evidence_lines, list) or not all(
            isinstance(line, str) and re.fullmatch(r"E\d+: .+", line)
            for line in allowed_evidence_lines
        ):
            return ["AGENT PLAN CONTROL is missing its factual evidence allowlist"]
        evidence_text = "\n".join(allowed_evidence_lines)

        for field in ("intent", "objective", "plan_step", "expected_simulation_result"):
            error = self._scalar_contract_error(
                payload.get(field),
                field,
                max_length=MAX_OBJECTIVE_LENGTH if field == "objective" else None,
            )
            if error:
                errors.append(error)

        last_review = payload.get("last_action_review")
        if not isinstance(last_review, dict):
            errors.append("last_action_review must be an object")
        else:
            previous_step = int(control.get("previous_step", -1))
            submitted_previous_step = last_review.get("previous_step")
            if type(submitted_previous_step) is not int:
                errors.append("last_action_review.previous_step must be an integer")
            elif submitted_previous_step != previous_step:
                errors.append(
                    "last_action_review.previous_step does not match AGENT PLAN CONTROL "
                    f"(expected {previous_step})"
                )

            expected_verdict = control.get("previous_verdict")
            if last_review.get("verdict") != expected_verdict:
                errors.append(
                    "last_action_review.verdict does not match AGENT PLAN CONTROL "
                    f"(expected {expected_verdict!r})"
                )

            retry_same_action = last_review.get("retry_same_action")
            retry_is_bool = type(retry_same_action) is bool
            if not retry_is_bool:
                errors.append("last_action_review.retry_same_action must be boolean")

            error = self._scalar_contract_error(
                last_review.get("lesson"), "last_action_review.lesson"
            )
            if error:
                errors.append(error)

            expected_previous_id = str(control.get("previous_evidence_id") or "")
            if re.fullmatch(r"E\d+", expected_previous_id) is None:
                errors.append("AGENT PLAN CONTROL is missing the required previous evidence id")
            last_evidence = last_review.get("evidence")
            if expected_previous_id and (
                not isinstance(last_evidence, list)
                or expected_previous_id not in last_evidence
            ):
                errors.append(
                    "last_action_review.evidence must include required evidence id "
                    f"{expected_previous_id!r}"
                )
            error = self._evidence_error(
                last_evidence, evidence_text, "last_action_review.evidence"
            )
            if error:
                errors.append(error)

            previous_fingerprint = str(control.get("previous_action_fingerprint") or "")
            if previous_step < 0:
                if retry_same_action is True:
                    errors.append(
                        "last_action_review.retry_same_action must be false on the initial step"
                    )
            elif not re.fullmatch(r"[0-9a-f]{64}", previous_fingerprint):
                errors.append("AGENT PLAN CONTROL is missing the previous action fingerprint")
            elif fingerprint_action is not None:
                repeats_previous_action = (
                    normalized_action_fingerprint(fingerprint_action)
                    == previous_fingerprint
                )
                if retry_is_bool and retry_same_action != repeats_previous_action:
                    errors.append(
                        "last_action_review.retry_same_action must match whether type+params "
                        "repeat the previous action "
                        f"(expected {str(repeats_previous_action).lower()})"
                    )

        plan_review = payload.get("plan_review")
        if not isinstance(plan_review, dict):
            errors.append("plan_review must be an object")
            return errors

        request_error = self._scalar_contract_error(
            plan_review.get("request_id"), "plan_review.request_id"
        )
        if request_error:
            errors.append(request_error)
        elif plan_review.get("request_id") != control.get("request_id"):
            errors.append(
                "plan_review.request_id does not match AGENT PLAN CONTROL "
                f"(expected {control.get('request_id')!r})"
            )

        prior = str(control.get("prior_objective") or "")
        prior_error = self._scalar_contract_error(
            plan_review.get("prior_objective"), "plan_review.prior_objective"
        )
        if plan_review.get("prior_objective") == "":
            prior_error = None
        if prior_error:
            errors.append(prior_error)
        else:
            if self._normalized_prior_objective(
                plan_review.get("prior_objective")
            ) != self._normalized_prior_objective(prior):
                errors.append(
                    "plan_review.prior_objective does not match AGENT PLAN CONTROL "
                    f"(expected {prior!r})"
                )

        objective = str(payload.get("objective") or "")
        plan_objective_error = self._scalar_contract_error(
            plan_review.get("objective"),
            "plan_review.objective",
            max_length=MAX_OBJECTIVE_LENGTH,
        )
        if plan_objective_error:
            errors.append(f"{plan_objective_error} (expected {objective!r})")
        elif self._normalized_objective(
            plan_review.get("objective")
        ) != self._normalized_objective(objective):
            errors.append(
                "plan_review.objective must equal objective "
                f"(expected {objective!r})"
            )

        steps = plan_review.get("steps")
        if steps is not None and (
            not isinstance(steps, list)
            or any(
                not isinstance(step, str)
                or not step.strip()
                or "\n" in step
                or "\r" in step
                for step in steps
            )
        ):
            errors.append("plan_review.steps must contain only non-empty single-line strings")

        decision = str(plan_review.get("decision") or "")
        valid_decisions = {"not_due", "establish", "continue", "revise", "complete"}
        decision_valid = decision in valid_decisions
        if not decision_valid:
            errors.append("plan_review.decision is invalid")
        reason = plan_review.get("reason")
        if decision != "not_due":
            error = self._scalar_contract_error(reason, "plan_review.reason")
            if error:
                errors.append(error)
        elif reason not in (None, ""):
            error = self._scalar_contract_error(reason, "plan_review.reason")
            if error:
                errors.append(error)

        plan_evidence = plan_review.get("evidence")
        evidence_error = self._evidence_error(
            plan_evidence, evidence_text, "plan_review.evidence"
        )
        if evidence_error:
            errors.append(evidence_error)
        if not isinstance(plan_evidence, list) or len(plan_evidence) < 2:
            errors.append(
                "plan_review.evidence requires at least two distinct allowed evidence ids (E#)"
            )
        plan_evidence_ready = evidence_error is None and len(plan_evidence) >= 2

        matched_lines: List[str] = []
        if plan_evidence_ready:
            matched_lines = [
                self._matching_evidence_line(str(quote), evidence_text) or ""
                for quote in plan_evidence
            ]
            if len(set(matched_lines)) != len(matched_lines):
                errors.append("plan_review.evidence must cite distinct factual lines")

        review_due = bool(control.get("review_due"))
        current_state_evidence_required = review_due or decision == "complete"
        if current_state_evidence_required and plan_evidence_ready:
            control_prefixes = (
                "AGENT PLAN CONTROL:",
                "Plan review reasons:",
                "Prior objective:",
                "Previous action attempt for review:",
                "Review evidence rule:",
            )
            matched_contents = [
                line.split(": ", 1)[-1] for line in matched_lines
            ]
            if all(line.startswith(control_prefixes) for line in matched_contents):
                if decision == "complete":
                    errors.append(
                        "decision=complete plan_review must cite at least one non-control "
                        "current game-state fact"
                    )
                else:
                    errors.append(
                        "a due plan_review must quote at least one current game-state fact"
                    )
        normalized_prior = self._normalized_prior_objective(prior)
        has_prior_objective = bool(normalized_prior)
        same_objective = self._normalized_objective(objective) == normalized_prior
        hard_revision_required = self._requires_hard_revision(control)
        if decision == "complete":
            if not has_prior_objective:
                errors.append("decision=complete requires an existing prior objective")
            elif same_objective:
                errors.append("decision=complete must change the prior objective")
        if hard_revision_required:
            if decision == "continue":
                errors.append(
                    "same_objective_stalled_2 requires decision=revise; "
                    "decision=continue is invalid"
                )
            elif decision != "revise":
                errors.append("same_objective_stalled_2 requires decision=revise")
            if same_objective:
                errors.append(
                    "same_objective_stalled_2 requires a genuinely different objective"
                )
            if (
                control.get("previous_verdict") in {"rejected", "no_progress"}
                and repeats_previous_action is True
            ):
                errors.append(
                    "same_objective_stalled_2 requires submitted action normalized type+params "
                    "to differ from the previous rejected/no-progress action"
                )
        if review_due and decision_valid and plan_objective_error is None:
            if not has_prior_objective and decision != "establish":
                errors.append("initial plan review must use decision=establish")
            if not hard_revision_required:
                if has_prior_objective and decision == "continue" and not same_objective:
                    errors.append("decision=continue must preserve the prior objective")
                if has_prior_objective and decision == "revise" and same_objective:
                    errors.append("decision=revise must change the prior objective")
                if has_prior_objective and decision not in {"continue", "revise", "complete"}:
                    errors.append(
                        "due plan review must continue, revise, or complete the prior objective"
                    )
        elif not review_due and decision_valid and plan_objective_error is None:
            if not hard_revision_required:
                if decision == "revise" and same_objective:
                    errors.append("decision=revise must change the prior objective")
                if not same_objective and decision not in {"revise", "complete"}:
                    errors.append(
                        "an objective change requires decision=revise or decision=complete; either "
                        "keep the submitted objective and use revise/complete, or restore the exact "
                        "prior objective and use not_due/continue"
                    )
                if same_objective and decision not in {"not_due", "continue"}:
                    errors.append(
                        "when review_due=no, unchanged objectives must use "
                        "decision=not_due or continue"
                    )
        return errors

    def decide(self, obs_text: str, obs_json: Dict[str, Any]) -> Dict[str, Any]:
        self._record_previous_outcome(obs_text)

        memory_context = self._memory.get_context()
        user_content = obs_text if not memory_context else f"{memory_context}\n\n{obs_text}"
        message_content: Any = user_content
        if self._vision and isinstance(obs_json, dict):
            fort = obs_json.get("fort")
            if isinstance(fort, dict):
                data_url = minimap_data_url(fort)
                if data_url:
                    message_content = [
                        {"type": "text", "text": user_content},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ]
                    self._tool_events.append(
                        {
                            "tool": "governed_llm.vision_minimap",
                            "input": {"rows": len(fort.get("map_rows") or [])},
                            "output": {"attached": True},
                        }
                    )
        messages = [
            {"role": "system", "content": GOVERNED_SYSTEM_PROMPT},
            {"role": "user", "content": GOVERNED_OBSERVATION_PREAMBLE},
            {"role": "user", "content": message_content},
        ]

        control = obs_json.get("agent_plan_control") if isinstance(obs_json, dict) else None
        review_control = control if isinstance(control, dict) else None
        max_contract_attempts = 3 if review_control is not None else 1
        action = None
        last_error = "model returned no submit_action tool call"
        locked_required_plan_decision: str | None = None
        for attempt in range(max_contract_attempts):
            contract_errors: List[str] = []
            try:
                response = self._create_completion(messages)
            except GovernedDecisionError:
                raise
            except Exception as exc:
                if review_control is not None:
                    raise RuntimeError(f"governed model call failed before gameplay: {exc}") from exc
                return self._store_pending(obs_text, self._fallback_wait(f"llm call failed: {exc}"))

            payload = self._extract_tool_payload(response)
            if payload is None:
                last_error = "model returned no submit_action tool call"
                contract_errors = [last_error]
            else:
                payload = self._normalize_provider_coordinate_wrappers(payload)
                payload = self._normalize_minimax_farm_seasons_wrapper(payload)
                payload = self._normalize_objective_quote_artifacts(payload)
                payload = self._normalize_duplicated_objective_length(payload)
                if review_control is not None:
                    payload = self._normalize_redundant_plan_decision(
                        payload, review_control
                    )
                action_type = str(payload.get("type") or "").upper()
                canonical_action = None
                fingerprint_action = None
                if action_type not in GOVERNED_ACTION_TYPES:
                    contract_errors.append(
                        f"illegal action type: {action_type or 'missing'}"
                    )
                else:
                    fingerprint_payload = {
                        "type": payload.get("type"),
                        "params": payload.get("params"),
                    }
                    if action_type == "INTERACT":
                        fingerprint_payload["advance_ticks"] = 0
                    try:
                        fingerprint_action = parse_action(
                            self._normalize_payload(fingerprint_payload),
                            max_advance_ticks=self._max_advance_ticks,
                        )
                    except (TypeError, ValueError):
                        pass
                    try:
                        canonical_action = parse_action(
                            self._normalize_payload(payload),
                            max_advance_ticks=self._max_advance_ticks,
                        )
                    except (TypeError, ValueError) as exc:
                        contract_errors.append(f"invalid action payload: {exc}")
                if review_control is not None:
                    contract_errors.extend(
                        self._review_contract_errors(
                            payload,
                            obs_text,
                            review_control,
                            fingerprint_action,
                        )
                    )
                    if locked_required_plan_decision is not None:
                        submitted_plan_decision = (
                            payload.get("plan_review", {}).get("decision")
                            if isinstance(payload.get("plan_review"), dict)
                            else None
                        )
                        if not self._decision_satisfies_requirement(
                            submitted_plan_decision,
                            locked_required_plan_decision,
                        ):
                            contract_errors.append(
                                "plan_review.decision violates locked first-correction "
                                f"requirement {locked_required_plan_decision!r} "
                                f"(submitted {submitted_plan_decision!r})"
                            )
                if contract_errors:
                    last_error = "; ".join(contract_errors)
                elif canonical_action is not None:
                    action = canonical_action
                    break
            if review_control is not None and attempt + 1 < max_contract_attempts:
                rejected_payload = (
                    json.dumps(payload, ensure_ascii=True, sort_keys=True)
                    if isinstance(payload, dict)
                    else "null"
                )
                submitted_objective = (
                    str(payload.get("objective") or "")
                    if isinstance(payload, dict)
                    else None
                )
                prior_objective = str(review_control.get("prior_objective") or "")
                hard_revision_required = self._requires_hard_revision(review_control)
                submitted_plan_decision = (
                    payload.get("plan_review", {}).get("decision")
                    if isinstance(payload, dict)
                    and isinstance(payload.get("plan_review"), dict)
                    else None
                )
                objective_matches_prior = (
                    self._normalized_objective(submitted_objective)
                    == self._normalized_objective(prior_objective)
                    if submitted_objective is not None
                    else None
                )
                if submitted_objective is None:
                    computed_required_plan_decision = None
                elif hard_revision_required:
                    computed_required_plan_decision = "revise"
                elif bool(
                    review_control.get("review_due")
                ) and not self._normalized_prior_objective(prior_objective):
                    computed_required_plan_decision = "establish"
                elif submitted_plan_decision == "complete":
                    computed_required_plan_decision = "complete"
                elif bool(review_control.get("review_due")):
                    computed_required_plan_decision = (
                        "continue" if objective_matches_prior else "revise"
                    )
                elif objective_matches_prior:
                    computed_required_plan_decision = "not_due or continue"
                else:
                    computed_required_plan_decision = "revise"
                if (
                    locked_required_plan_decision is None
                    and computed_required_plan_decision is not None
                ):
                    locked_required_plan_decision = computed_required_plan_decision
                required_plan_decision = (
                    locked_required_plan_decision or computed_required_plan_decision
                )
                detected_errors = contract_errors or [last_error]
                evidence_correction_needed = any(
                    "evidence" in error.lower()
                    or "current game-state fact" in error.lower()
                    for error in detected_errors
                )
                if required_plan_decision in {
                    "establish",
                    "continue",
                    "revise",
                    "complete",
                }:
                    decision_correction_needed = (
                        submitted_plan_decision != required_plan_decision
                    )
                elif required_plan_decision == "not_due or continue":
                    decision_correction_needed = submitted_plan_decision not in {
                        "not_due",
                        "continue",
                    }
                else:
                    decision_correction_needed = False
                objective_correction_needed = any(
                    error.lower().startswith(("objective ", "plan_review.objective "))
                    for error in detected_errors
                )
                expected_values: Dict[str, Any] = {
                    "plan_request_id": review_control.get("request_id"),
                    "previous_step": review_control.get("previous_step"),
                    "previous_verdict": review_control.get("previous_verdict"),
                    "prior_objective": prior_objective,
                    "plan_review_reasons": review_control.get("reasons"),
                    "locked_required_plan_decision": locked_required_plan_decision,
                    "required_plan_decision_for_submitted_objective": required_plan_decision,
                    "required_previous_evidence_id": review_control.get(
                        "previous_evidence_id"
                    ),
                    "submitted_objective": submitted_objective,
                    "submitted_objective_matches_prior": objective_matches_prior,
                    "submitted_plan_decision": submitted_plan_decision,
                }
                repair_instructions: List[str] = []
                if hard_revision_required:
                    repair_instructions.append(
                        "Required hard transition for reason 'same_objective_stalled_2': "
                        "decision=continue is invalid. Set plan_review.decision exactly to 'revise', "
                        "keep prior_objective unchanged, ensure objective and plan_review.objective "
                        "name the same genuinely different current objective, and submit an action "
                        "that advances that replacement. Its normalized type+params must differ "
                        "from the previous rejected/no-progress action even when "
                        "retry_same_action=true. Renaming the stalled objective or selecting another "
                        "target for the same rejected approach is not a revision. The harness does "
                        "not choose the replacement."
                    )
                elif required_plan_decision == "complete":
                    repair_instructions.append(
                        "Preserve plan_review.decision exactly as 'complete'; do not change it to "
                        "continue or revise. Keep prior_objective as the completed objective, set "
                        "objective and plan_review.objective to the same genuinely different next "
                        "objective, submit an action that advances only that next objective, and cite "
                        "at least one non-control current game-state evidence id supporting completion."
                    )
                elif (
                    decision_correction_needed
                    and not objective_correction_needed
                    and required_plan_decision
                    in {
                        "establish",
                        "continue",
                        "revise",
                    }
                ):
                    repair_instructions.append(
                        "Required decision repair: preserve the submitted objective and set "
                        f"plan_review.decision exactly to {required_plan_decision!r}."
                    )
                elif (
                    decision_correction_needed
                    and not objective_correction_needed
                    and required_plan_decision == "not_due or continue"
                ):
                    repair_instructions.append(
                        "Required decision repair: preserve the submitted objective and set "
                        "plan_review.decision to either 'not_due' or 'continue'."
                    )
                if evidence_correction_needed:
                    allowed_evidence_lines = [
                        line
                        for line in review_control.get("allowed_evidence_lines", [])
                        if isinstance(line, str) and re.fullmatch(r"E\d+: .+", line)
                    ]
                    expected_values["allowed_evidence_ids"] = [
                        line.split(": ", 1)[0] for line in allowed_evidence_lines
                    ]
                    expected_values["allowed_evidence_lines"] = allowed_evidence_lines
                    repair_instructions.append(
                        "Evidence fields must contain only E# identifiers, never copied "
                        "observation text. Set last_action_review.evidence to a JSON array "
                        "that includes required_previous_evidence_id. Set "
                        "plan_review.evidence to a JSON array containing at least two distinct "
                        "allowed_evidence_ids that factually support the plan review."
                    )
                expected_control = json.dumps(
                    expected_values,
                    ensure_ascii=True,
                    sort_keys=True,
                )
                validation_feedback = "\n".join(
                    f"- {error}" for error in detected_errors
                )
                focused_repairs = " ".join(repair_instructions)
                self._tool_events.append(
                    {
                        "tool": "governed_llm.review_contract_retry",
                        "input": {"request_id": review_control.get("request_id")},
                        "output": {
                            "error": last_error,
                            "errors": contract_errors or [last_error],
                        },
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your most recent submit_action was rejected before gameplay. "
                            "Correct this exact payload and preserve every field that already "
                            f"satisfies the contract:\n{rejected_payload}\n"
                            "Validation errors (all currently detected):\n"
                            f"{validation_feedback}\n"
                            f"Authoritative AGENT PLAN CONTROL values: {expected_control}\n"
                            f"{focused_repairs} "
                            "Re-read AGENT PLAN CONTROL and "
                            "return one corrected submit_action. No game ticks have advanced."
                        ),
                    }
                )

        if action is None:
            if review_control is not None:
                raise GovernedReviewContractError(
                    "governed review contract failed before gameplay after two corrections: "
                    + last_error,
                    corrections=max_contract_attempts - 1,
                    contract_error=last_error,
                )
            return self._store_pending(obs_text, self._fallback_wait(last_error))

        self._apply_memory_fields(action)
        return self._store_pending(obs_text, action)

    def _store_pending(self, obs_text: str, action: Dict[str, Any]) -> Dict[str, Any]:
        digest = (obs_text or "").strip().splitlines()
        self._pending = {
            "observation_digest": " | ".join(line for line in digest[:3] if line),
            "action": action,
        }
        self._save_memory()
        return action

    def _extract_tool_payload(self, response: Any) -> Optional[Dict[str, Any]]:
        try:
            choices = getattr(response, "choices", None) or []
            message = getattr(choices[0], "message", None)
            tool_calls = getattr(message, "tool_calls", None) or []
        except (IndexError, AttributeError):
            return None
        self._record_response_telemetry(response, choices)
        for call in tool_calls:
            function = getattr(call, "function", None)
            if getattr(function, "name", "") != "submit_action":
                continue
            try:
                arguments = json.loads(getattr(function, "arguments", "") or "{}")
            except json.JSONDecodeError:
                return None
            return arguments if isinstance(arguments, dict) else None
        # some providers (e.g. Kimi with mandatory reasoning) answer with the
        # action as JSON in the text body instead of a tool call
        payload = self._json_payload_from_text(getattr(message, "content", None))
        if payload is not None:
            self._tool_events.append(
                {
                    "tool": "governed_llm.text_payload_fallback",
                    "input": {"model": self._model},
                    "output": {"parsed": True},
                }
            )
        return payload

    @staticmethod
    def _field(value: Any, name: str, default: Any = None) -> Any:
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    @classmethod
    def _plain_mapping(cls, value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return dict(value)
        dump = getattr(value, "model_dump", None)
        if callable(dump):
            data = dump()
            return dict(data) if isinstance(data, dict) else {}
        data = getattr(value, "__dict__", None)
        return dict(data) if isinstance(data, dict) else {}

    def _generation_metadata(self, generation_id: str | None) -> Dict[str, Any]:
        if not generation_id:
            return {"status": "unavailable", "reason": "missing_generation_id"}
        try:
            httpx = import_module("httpx")
            base_url = str(self._settings.OPENROUTER_BASE_URL).rstrip("/")
            response = httpx.get(
                f"{base_url}/generation",
                params={"id": generation_id},
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=min(float(self._settings.OPENROUTER_TIMEOUT_SECONDS), 10.0),
            )
            response.raise_for_status()
            body = response.json()
            data = body.get("data") if isinstance(body, dict) else None
            if not isinstance(data, dict):
                return {"status": "unavailable", "reason": "invalid_generation_payload"}
            return {
                "status": "available",
                "provider_name": data.get("provider_name") or data.get("provider"),
                "model": data.get("model"),
                "total_cost": data.get("total_cost"),
                "upstream_inference_cost": data.get("upstream_inference_cost"),
                "cache_discount": data.get("cache_discount"),
                "native_tokens_prompt": data.get("native_tokens_prompt"),
                "native_tokens_completion": data.get("native_tokens_completion"),
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "reason": type(exc).__name__,
                "message": str(exc)[:240],
            }

    def _record_response_telemetry(self, response: Any, choices: List[Any]) -> None:
        usage = self._field(response, "usage")
        prompt_details = self._plain_mapping(self._field(usage, "prompt_tokens_details"))
        completion_details = self._plain_mapping(
            self._field(usage, "completion_tokens_details")
        )
        generation_id = self._field(response, "id")
        finish_reasons = [
            self._field(choice, "finish_reason")
            for choice in choices
            if self._field(choice, "finish_reason") is not None
        ]
        self._tool_events.append(
            {
                "tool": "openrouter.chat.completions.create",
                "input": {
                    "model": self._model,
                    "session_id": self._session_id,
                    "reasoning_effort": self._reasoning_effort,
                    "prompt_cache": self._prompt_cache or "automatic",
                    "max_tokens": self._max_tokens or self._settings.LLM_MAX_TOKENS,
                    "vision": self._vision,
                },
                "output": {
                    "generation_id": generation_id,
                    "resolved_model": self._field(response, "model"),
                    "finish_reasons": finish_reasons,
                    "prompt_tokens": self._field(usage, "prompt_tokens"),
                    "completion_tokens": self._field(usage, "completion_tokens"),
                    "total_tokens": self._field(usage, "total_tokens"),
                    "cached_tokens": prompt_details.get("cached_tokens"),
                    "cache_write_tokens": prompt_details.get("cache_write_tokens"),
                    "reasoning_tokens": completion_details.get("reasoning_tokens"),
                    "cost": self._field(usage, "cost"),
                    "cost_details": self._plain_mapping(self._field(usage, "cost_details")),
                    "is_byok": self._field(usage, "is_byok"),
                    "generation": self._generation_metadata(generation_id),
                },
            }
        )

    @staticmethod
    def _json_payload_from_text(content: Any) -> Optional[Dict[str, Any]]:
        """Extract an action-shaped JSON object from plain response text."""

        if isinstance(content, list):
            content = " ".join(
                str(part.get("text", "")) for part in content if isinstance(part, dict)
            )
        if not isinstance(content, str) or "{" not in content:
            return None
        decoder = json.JSONDecoder()
        index = content.find("{")
        while index != -1:
            try:
                candidate, _ = decoder.raw_decode(content, index)
            except json.JSONDecodeError:
                index = content.find("{", index + 1)
                continue
            if (
                isinstance(candidate, dict)
                and str(candidate.get("type", "")).upper() in GOVERNED_ACTION_TYPES
            ):
                return candidate
            index = content.find("{", index + 1)
        return None

    def pop_tool_events(self) -> List[Dict[str, Any]]:
        events = self._tool_events
        self._tool_events = []
        return events


register_agent("dfhack-governed-llm", lambda: DFHackGovernedLLMAgent())
# Pinned variants: the registry name itself declares the serving model, immune
# to environment drift (OPENROUTER_MODEL in a deployment env file overrides
# the repo default AND systemd drop-ins — discovered 2026-07-03 when every
# governed run to date turned out to be served by an env-file override).
register_agent(
    "dfhack-governed-llm-glm52",
    lambda: DFHackGovernedLLMAgent(model_override="z-ai/glm-5.2", max_tokens=1024),
)
register_agent(
    "dfhack-governed-llm-deepseek-v4",
    lambda: DFHackGovernedLLMAgent(model_override="deepseek/deepseek-v4-pro"),
)
register_agent(
    "dfhack-governed-llm-gpt55",
    lambda: DFHackGovernedLLMAgent(model_override="openai/gpt-5.5"),
)
register_agent(
    "dfhack-governed-llm-fable5",
    lambda: DFHackGovernedLLMAgent(
        model_override="anthropic/claude-fable-5",
        memory_path=None,
        vision=True,
        max_tokens=128000,
        reasoning_effort="max",
        prompt_cache="explicit_ephemeral",
        omit_temperature=True,
        memory_window=0,
        max_advance_ticks=2500,
    ),
)
register_agent(
    "dfhack-governed-llm-gpt56-sol",
    lambda: DFHackGovernedLLMAgent(
        model_override="openai/gpt-5.6-sol",
        memory_path=None,
        vision=True,
        max_tokens=128000,
        reasoning_effort="max",
        prompt_cache="automatic",
        memory_window=0,
        max_advance_ticks=2500,
    ),
)
# Vision variants: the same governed surface, with the fort minimap attached
# as a rendered PNG (same grid, different modality).
register_agent(
    "dfhack-governed-llm-glm5v",
    # Governed review payloads exceeded the default 512-token ceiling in G7
    # attempt 8; the exact terminal observation completed validly in 830 tokens.
    lambda: DFHackGovernedLLMAgent(
        model_override="z-ai/glm-5v-turbo", vision=True, max_tokens=1024
    ),
)
register_agent(
    "dfhack-governed-llm-gpt55-vision",
    lambda: DFHackGovernedLLMAgent(model_override="openai/gpt-5.5", vision=True),
)
register_agent(
    "dfhack-governed-llm-kimi-vision",
    # mandatory reasoning consumes the default 512-token budget on real-sized
    # observations before the tool call is emitted; give it headroom
    lambda: DFHackGovernedLLMAgent(
        model_override="moonshotai/kimi-k2.7-code", vision=True, max_tokens=4096
    ),
)
register_agent(
    "dfhack-governed-llm-minimax-vision",
    lambda: DFHackGovernedLLMAgent(model_override="minimax/minimax-m3", vision=True),
)
register_agent(
    "dfhack-governed-llm-minimax-canary",
    # Keep the diagnostic arm on the same generation envelope as a full P1
    # run. Its lower spend comes from the model price, not reduced headroom.
    lambda: DFHackGovernedLLMAgent(
        model_override="minimax/minimax-m3",
        memory_path=None,
        vision=True,
        max_tokens=128000,
        reasoning_effort="max",
        prompt_cache="automatic",
        memory_window=0,
        max_advance_ticks=2500,
    ),
)


__all__ = [
    "DFHackGovernedLLMAgent",
    "GOVERNED_ACTION_TYPES",
    "GOVERNED_OBSERVATION_PREAMBLE",
    "GOVERNED_SYSTEM_PROMPT",
]

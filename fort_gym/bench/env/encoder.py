"""Observation encoding utilities."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

INVALID_DF_CURSOR = -30000
MENU_ESCAPE_OBSERVATION_RULE = (
    "If escaping this screen, submit only LEAVESCREEN keys with advance_ticks=0; "
    "do not combine LEAVESCREEN with a later menu/action key until the next "
    "observation confirms the screen."
)


def redact_noise(state: Dict[str, Any]) -> Dict[str, Any]:
    """Placeholder hook to strip non-deterministic noise from raw state."""
    return state


def _is_inactive_df_cursor(value: Any) -> bool:
    try:
        return int(value) <= INVALID_DF_CURSOR
    except (TypeError, ValueError):
        return False


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _work_int(work: Dict[str, Any], key: str, default: int = 0) -> int:
    value = _int_or_none(work.get(key))
    return default if value is None else value


def _int_list_or_none(value: Any, length: int) -> List[int] | None:
    if not isinstance(value, list) or len(value) < length:
        return None
    ints: List[int] = []
    for item in value[:length]:
        parsed = _int_or_none(item)
        if parsed is None:
            return None
        ints.append(parsed)
    return ints


def _render_int_list(values: List[int]) -> str:
    return "[" + ",".join(str(value) for value in values) + "]"


def _sanitize_token(value: str, limit: int = 32) -> str:
    """Keep short evidence tokens (season names, skip reasons) printable.

    Values arrive from a lua hook that already CP437-sanitizes, but keep a
    conservative whitelist here so a stray character cannot corrupt the
    single-line observation. Non-whitelisted characters are dropped.
    """
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in {"_", "-", " "}).strip()
    return cleaned[:limit]


def _proven_carpenter_workshops(work: Dict[str, Any]) -> int:
    if "carpenter_workshops_usable" in work:
        return _work_int(work, "carpenter_workshops_usable")
    return _work_int(work, "carpenter_workshops")


def _screen_text_lines(screen_text: str) -> List[str]:
    return [
        line.strip()
        for line in screen_text.splitlines()
        if line.strip() and not line.startswith("== SCREEN VISUAL HINTS ==")
    ]


def _screen_visual_hint_texts(screen_text: str) -> List[str]:
    hints: List[str] = []
    in_hints = False
    for line in screen_text.splitlines():
        stripped = line.strip()
        if stripped == "== SCREEN VISUAL HINTS ==":
            in_hints = True
            continue
        if not in_hints or not stripped.startswith("- row "):
            continue
        _, _, text = stripped.partition(": ")
        if text:
            hints.append(text.strip())
    return hints


def _classify_screen_state(screen_text: Optional[str]) -> Dict[str, Any]:
    if not screen_text:
        return {}

    lower = screen_text.lower()
    lines = _screen_text_lines(screen_text)
    visual_hints = _screen_visual_hint_texts(screen_text)
    highlighted = visual_hints[0] if visual_hints else None
    evidence: List[str] = []

    def result(
        mode: str,
        *,
        confidence: str = "medium",
        instruction: str | None = None,
        extra_evidence: List[str] | None = None,
    ) -> Dict[str, Any]:
        facts = list(extra_evidence or evidence)
        if highlighted:
            facts.append(f"highlighted={highlighted}")
        return {
            "mode": mode,
            "confidence": confidence,
            "highlighted": highlighted,
            "evidence": facts[:5],
            "instruction": instruction,
        }

    if "manager is required" in lower:
        return result(
            "manager_required",
            confidence="high",
            instruction=(
                "Do not advance time for production yet. Use visible evidence to "
                "appoint a manager or choose a direct workshop-task path. "
                f"{MENU_ESCAPE_OBSERVATION_RULE}"
            ),
            extra_evidence=["visible text says a manager is required"],
        )

    if "d: designations" in lower and "b: building" in lower:
        return result(
            "main_map",
            confidence="medium",
            instruction="Main map/menu view; choose a productive action directly.",
            extra_evidence=["visible main map command menu"],
        )

    if "nobles and administrators" in lower or (
        "administrator" in lower and "manager" in lower and "appoint" in lower
    ):
        return result(
            "nobles_administrators",
            confidence="high",
            instruction=(
                "Use visible row/highlight evidence before selecting a noble. "
                "Do not use STANDARDSCROLL keys here. Do not use fixed row "
                "counts unless the target row is visible and highlighted. "
                f"{MENU_ESCAPE_OBSERVATION_RULE}"
            ),
            extra_evidence=["visible Nobles/Administrators screen"],
        )

    if "m: manager" in lower and ("view job" in lower or "set job repeat" in lower):
        return result(
            "job_list",
            confidence="high",
            instruction=(
                "Visible jobs screen. If production orders are needed, use "
                "UNITJOB_MANAGER from this screen before manager-order keys. "
                f"{MENU_ESCAPE_OBSERVATION_RULE}"
            ),
            extra_evidence=["visible jobs screen footer includes m: Manager"],
        )

    if "new order" in lower and (
        "enter: select" in lower or "search" in lower or "work order" in lower
    ):
        useful_rows = [
            line
            for line in lines
            if any(
                item in line.lower()
                for item in (
                    "construct bed",
                    "construct door",
                    "construct table",
                    "construct chair",
                    "make wooden barrel",
                    "make wooden bin",
                )
            )
        ]
        return result(
            "manager_new_order_search",
            confidence="high",
            instruction=(
                "If exactly one useful highlighted result is visible, SELECT can "
                "queue it. If the search result is wrong or stale, record the "
                "search as failed and reopen a clean dialog before another term. "
                f"{MENU_ESCAPE_OBSERVATION_RULE}"
            ),
            extra_evidence=useful_rows[:3] or ["visible manager new-order search"],
        )

    if "manager" in lower and ("work order" in lower or "new order" in lower or "orders" in lower):
        return result(
            "manager_orders",
            confidence="medium",
            instruction=(
                "Use MANAGER_NEW_ORDER only when this screen is the manager/work "
                "orders screen; otherwise exit and re-enter through D_JOBLIST. "
                f"{MENU_ESCAPE_OBSERVATION_RULE}"
            ),
            extra_evidence=["visible manager/order text"],
        )

    if "carpenter's workshop" in lower and (
        "enter: select" in lower and "item" in lower and "dist" in lower and "num" in lower
    ):
        return result(
            "workshop_material_selection",
            confidence="high",
            instruction=(
                "SELECT chooses the highlighted material row if no Needs building "
                "material warning is visible. "
                f"{MENU_ESCAPE_OBSERVATION_RULE}"
            ),
            extra_evidence=["visible carpenter workshop material list"],
        )

    if "carpenter's workshop" in lower and "placement" in lower:
        blocked = (
            "blocked" in lower or "building present" in lower or "needs building material" in lower
        )
        return result(
            "workshop_placement",
            confidence="high",
            instruction=(
                "Do not SELECT while placement is blocked or missing material. "
                f"{MENU_ESCAPE_OBSERVATION_RULE}"
                if blocked
                else (
                    "SELECT can place the workshop if your screen_read confirms "
                    f"Enter: Place. {MENU_ESCAPE_OBSERVATION_RULE}"
                )
            ),
            extra_evidence=[
                "visible blocked workshop placement"
                if blocked
                else "visible workshop placement screen"
            ],
        )

    if "carpenter's workshop" in lower and (
        "waiting for construction" in lower
        or "construction inactive" in lower
        or "s: suspend construction" in lower
    ):
        return result(
            "carpenter_workshop_construction_pending",
            confidence="high",
            instruction=(
                "Visible Carpenter's Workshop construction-pending screen. This "
                "is not the usable task menu and BUILDJOB_ADD will not queue "
                "production from here. Treat carpenter_workshops/planned as "
                "placement only until usable/task proof appears; inspect or fix "
                "the construction blocker before claiming production. "
                f"{MENU_ESCAPE_OBSERVATION_RULE}"
            ),
            extra_evidence=["visible workshop says construction is pending"],
        )

    if "carpenter's workshop" in lower and (
        "leather works" in lower
        or "mason's workshop" in lower
        or "bowyer's workshop" in lower
        or "metalsmith's forge" in lower
    ):
        return result(
            "building_workshop_type_menu",
            confidence="high",
            instruction=(
                "Visible building workshop-type menu. If a workshop is already "
                "placed or construction is queued, do not select another "
                "workshop type here. Use only LEAVESCREEN with advance_ticks=0, "
                "then wait for the next observation before advancing time or "
                "inspecting the placed workshop."
            ),
            extra_evidence=["visible building workshop-type menu"],
        )

    task_rows = [
        line
        for line in lines
        if any(
            item in line.lower()
            for item in (
                "construct bed",
                "make wooden",
                "construct door",
                "construct table",
                "construct chair",
            )
        )
    ]
    if "carpenter's workshop" in lower and task_rows:
        return result(
            "workshop_add_task_list",
            confidence="high",
            instruction=(
                "SELECT chooses the highlighted task row. Use STANDARDSCROLL "
                "keys, not CURSOR_DOWN/CURSOR_UP, to change highlighted rows in "
                "a '+-*/: Scroll' list. Do not use BUILDJOB_ADD or raw letter "
                f"keys from this list. {MENU_ESCAPE_OBSERVATION_RULE}"
            ),
            extra_evidence=task_rows[:3] or ["visible carpenter workshop task list"],
        )

    if "carpenter's workshop" in lower and (
        "x: remove building" in lower or "ctrl+n: give name" in lower or "esc: done" in lower
    ):
        return result(
            "carpenter_workshop_selected",
            confidence="high",
            instruction=(
                "Visible selected Carpenter's Workshop screen. If no task, "
                "manager order, or active job is queued, do not leave and wait; "
                "use BUILDJOB_ADD to open the native add-task list. Status text "
                "such as Waiting for construction, Needs Carpentry, or "
                "Construction inactive means production is not queued yet; it is "
                "not a reason to place another workshop. "
                f"{MENU_ESCAPE_OBSERVATION_RULE}"
            ),
            extra_evidence=["visible selected Carpenter's Workshop screen"],
        )

    return result(
        "unknown",
        confidence="low",
        instruction="Use screen_read evidence before manual cursor/menu actions.",
        extra_evidence=lines[:2],
    )


def _compute_screen_diff(prev: str, curr: str) -> Dict[str, Any]:
    """Compare two screen captures and return diff info."""
    if not prev or not curr:
        return {"has_prev": False}

    prev_lines = prev.strip().split("\n")
    curr_lines = curr.strip().split("\n")

    # Count changed lines (ignoring minor whitespace)
    changed_lines = 0
    total_lines = max(len(prev_lines), len(curr_lines))

    for i in range(total_lines):
        p = prev_lines[i].strip() if i < len(prev_lines) else ""
        c = curr_lines[i].strip() if i < len(curr_lines) else ""
        if p != c:
            changed_lines += 1

    # Find cursor position (X marker) in both
    def find_cursor(lines: List[str]) -> Optional[Tuple[int, int]]:
        for row, line in enumerate(lines):
            # Look for X in the map area (typically left portion before menu)
            col = line.find("X")
            if col != -1 and col < 50:  # X in map area, not menu text
                return (row, col)
        return None

    prev_cursor = find_cursor(prev_lines)
    curr_cursor = find_cursor(curr_lines)

    cursor_moved = prev_cursor != curr_cursor

    return {
        "has_prev": True,
        "changed_lines": changed_lines,
        "total_lines": total_lines,
        "change_pct": (changed_lines / total_lines * 100) if total_lines > 0 else 0,
        "screen_identical": changed_lines == 0,
        "cursor_moved": cursor_moved,
        "prev_cursor": prev_cursor,
        "curr_cursor": curr_cursor,
    }


def _format_key_preview(keys: Any, limit: int = 5) -> str:
    if not isinstance(keys, list):
        return ""
    preview = keys[:limit]
    keys_str = ", ".join(str(key) for key in preview)
    if len(keys) > limit:
        keys_str += f"... (+{len(keys) - limit} more)"
    return keys_str


def _format_action_preview(action_entry: Dict[str, Any]) -> str:
    keys_str = _format_key_preview(action_entry.get("keys", []))
    action_type = str(action_entry.get("action_type") or "").strip()
    if not action_type or action_type == "KEYSTROKE":
        return keys_str
    params = action_entry.get("params")
    param_parts = []
    if isinstance(params, dict):
        param_parts = [f"{key}={value}" for key, value in params.items()]
    return action_type + ("(" + ", ".join(param_parts) + ")" if param_parts else "")


def _format_action_history_entry(action_entry: Dict[str, Any]) -> str:
    step_num = action_entry.get("step", "?")
    intent = action_entry.get("intent", "no intent")
    action_preview = _format_action_preview(action_entry)
    requested_ticks = action_entry.get(
        "requested_ticks",
        action_entry.get("advance_ticks", 0),
    )
    actual_ticks = action_entry.get("actual_ticks")
    accepted = action_entry.get("accepted")
    outcome = action_entry.get("outcome")
    changed = action_entry.get("changed")
    reasons = action_entry.get("productive_reasons")
    screen_read = (
        action_entry.get("screen_read") if isinstance(action_entry.get("screen_read"), dict) else {}
    )
    last_action_review = (
        action_entry.get("last_action_review")
        if isinstance(action_entry.get("last_action_review"), dict)
        else {}
    )

    details = [f"requested={requested_ticks}t"]
    if actual_ticks is not None:
        details.append(f"actual={actual_ticks}t")
    if accepted is not None:
        details.append("accepted=yes" if accepted else "accepted=no")
    if outcome:
        details.append(f"outcome={outcome}")
    error = action_entry.get("error")
    if error:
        details.append(f"error={error}")
    result_details = action_entry.get("result_details")
    if isinstance(result_details, dict) and result_details:
        result_text = ",".join(
            f"{key}={value}" for key, value in result_details.items()
        )
        details.append("result=" + result_text)
    placed_targets = action_entry.get("placed_targets")
    if isinstance(placed_targets, list) and placed_targets:
        details.append("placed=" + ",".join(str(item) for item in placed_targets))
    failed_targets = action_entry.get("failed_targets")
    if isinstance(failed_targets, list) and failed_targets:
        details.append("failed=" + ",".join(str(item) for item in failed_targets))
    if isinstance(reasons, list) and reasons:
        details.append("reasons=" + ",".join(str(reason) for reason in reasons[:4]))
    if isinstance(changed, list):
        details.append(
            "changed=" + (", ".join(str(item) for item in changed[:6]) if changed else "none")
        )
    before_order_qty = action_entry.get("order_qty_left_before")
    after_order_qty = action_entry.get("order_qty_left_after")
    if before_order_qty is not None and after_order_qty is not None:
        details.append(f"order_qty_left={before_order_qty}->{after_order_qty}")
    if screen_read:
        mode = str(screen_read.get("mode") or "").strip()
        confidence = str(screen_read.get("confidence") or "").strip()
        if mode:
            details.append("agent_screen=" + mode + (f"/{confidence}" if confidence else ""))
    if last_action_review:
        worked = last_action_review.get("worked")
        if worked is not None:
            details.append(f"agent_prev_worked={worked}")
        if last_action_review.get("should_retry_same_path") is not None:
            details.append(
                "agent_retry_same_path="
                + str(last_action_review.get("should_retry_same_path")).lower()
            )

    return f"  Step {step_num}: {intent} -> [{action_preview}] ({'; '.join(details)})"


def _format_last_action_command(step: Any, action: Dict[str, Any]) -> str:
    params = action.get("params") if isinstance(action.get("params"), dict) else {}
    entry = {
        "action_type": action.get("type"),
        "params": {
            key: value for key, value in params.items() if key != "keys" and value is not None
        },
        "keys": params.get("keys", []),
    }
    intent = str(action.get("intent") or "").strip()
    command = f"step={step} {_format_action_preview(entry)}"
    return command + (f"; intent={intent}" if intent else "")


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _key_fingerprint(keys: Any) -> str:
    if not isinstance(keys, list) or not keys:
        return "none"
    return " ".join(str(key) for key in keys[:12])


def _action_family(entry: Dict[str, Any]) -> str:
    keys = entry.get("keys")
    key_values = [str(key) for key in keys] if isinstance(keys, list) else []
    key_set = set(key_values)
    intent = str(entry.get("intent") or "").lower()

    if "D_DESIGNATE" in key_set:
        return "designation"
    if "D_BUILDING" in key_set:
        return "building_placement_menu"
    if "D_JOBLIST" in key_set or "UNITJOB_MANAGER" in key_set:
        return "job_manager_menu"
    if "D_NOBLES" in key_set or "nobles" in intent or "manager" in intent:
        return "manager_nobles_menu"
    if (
        "D_BUILDJOB" in key_set
        or "BUILDJOB_ADD" in key_set
        or "workshop task" in intent
        or "carpenter workshop" in intent
    ):
        return "workshop_task_menu"
    if any(key == "STRING_A032" for key in key_values):
        return "wait"
    navigation_keys = {
        "LEAVESCREEN",
        "SELECT",
        "CURSOR_UP",
        "CURSOR_DOWN",
        "CURSOR_LEFT",
        "CURSOR_RIGHT",
        "SECONDSCROLL_UP",
        "SECONDSCROLL_DOWN",
        "STANDARDSCROLL_UP",
        "STANDARDSCROLL_DOWN",
        "STANDARDSCROLL_PAGEUP",
        "STANDARDSCROLL_PAGEDOWN",
    }
    if key_values and all(key in navigation_keys for key in key_values):
        return "menu_navigation"
    return key_values[0] if key_values else "none"


def _is_escape_only_action(entry: Dict[str, Any]) -> bool:
    keys = entry.get("keys")
    return bool(isinstance(keys, list) and keys and all(str(key) == "LEAVESCREEN" for key in keys))


def _is_blockable_menu_family(family: str) -> bool:
    return family in {
        "building_placement_menu",
        "workshop_task_menu",
        "job_manager_menu",
        "manager_nobles_menu",
    }


def _recent_progress_summary(
    action_history: Optional[List[Dict[str, Any]]],
    work: Dict[str, Any],
) -> Dict[str, Any]:
    if not action_history:
        return {}

    last_productive_step = None
    last_progress_kind = None
    for entry in reversed(action_history):
        reasons = entry.get("productive_reasons")
        if isinstance(reasons, list) and reasons:
            last_productive_step = entry.get("step")
            last_progress_kind = str(reasons[0])
            break

    no_progress_streak = 0
    tick_no_progress_streak = 0
    no_progress_entries: List[Dict[str, Any]] = []
    for entry in reversed(action_history):
        reasons = entry.get("productive_reasons")
        productive = isinstance(reasons, list) and bool(reasons)
        if productive:
            break
        no_progress_entries.append(entry)
        no_progress_streak += 1
        if _to_int(entry.get("actual_ticks")) > 0:
            tick_no_progress_streak += 1

    menu_no_progress_entries: List[Dict[str, Any]] = []
    for entry in reversed(action_history):
        reasons = entry.get("productive_reasons")
        if isinstance(reasons, list) and reasons:
            break
        family = _action_family(entry)
        if family in {"designation", "wait"}:
            break
        if family != "none":
            menu_no_progress_entries.append(entry)

    menu_no_progress_streak = len(menu_no_progress_entries)
    family_counts: Dict[str, int] = {}
    fingerprint_counts: Dict[str, int] = {}
    agent_marked_bad_path = False
    for entry in menu_no_progress_entries:
        family = _action_family(entry)
        family_counts[family] = family_counts.get(family, 0) + 1
        fingerprint = _key_fingerprint(entry.get("keys"))
        fingerprint_counts[fingerprint] = fingerprint_counts.get(fingerprint, 0) + 1
        review = entry.get("last_action_review")
        if isinstance(review, dict) and review.get("should_retry_same_path") is False:
            agent_marked_bad_path = True

    repeated_menu_family = None
    repeated_menu_family_count = 0
    if family_counts:
        repeated_menu_family, repeated_menu_family_count = max(
            family_counts.items(),
            key=lambda item: item[1],
        )
    repeated_key_fingerprint = None
    repeated_key_fingerprint_count = 0
    if fingerprint_counts:
        repeated_key_fingerprint, repeated_key_fingerprint_count = max(
            fingerprint_counts.items(),
            key=lambda item: item[1],
        )

    sticky_family_counts: Dict[str, int] = {}
    sticky_fingerprint_counts: Dict[str, int] = {}
    sticky_agent_marked_bad_path = False
    for entry in no_progress_entries:
        family = _action_family(entry)
        if not _is_blockable_menu_family(family):
            continue
        sticky_family_counts[family] = sticky_family_counts.get(family, 0) + 1
        fingerprint = _key_fingerprint(entry.get("keys"))
        sticky_fingerprint_counts[fingerprint] = sticky_fingerprint_counts.get(fingerprint, 0) + 1
        review = entry.get("last_action_review")
        if isinstance(review, dict) and review.get("should_retry_same_path") is False:
            sticky_agent_marked_bad_path = True

    sticky_repeated_menu_family = None
    sticky_repeated_menu_family_count = 0
    if sticky_family_counts:
        sticky_repeated_menu_family, sticky_repeated_menu_family_count = max(
            sticky_family_counts.items(),
            key=lambda item: item[1],
        )
    sticky_repeated_key_fingerprint = None
    sticky_repeated_key_fingerprint_count = 0
    if sticky_fingerprint_counts:
        sticky_repeated_key_fingerprint, sticky_repeated_key_fingerprint_count = max(
            sticky_fingerprint_counts.items(),
            key=lambda item: item[1],
        )
    last_entry = action_history[-1]
    last_key_fingerprint = _key_fingerprint(last_entry.get("keys"))
    last_action_family = _action_family(last_entry)
    escape_recovery_attempted = any(_is_escape_only_action(entry) for entry in no_progress_entries)

    manager_orders = _to_int(work.get("manager_orders_count"))
    order_qty_left = _to_int(work.get("manager_orders_amount_left"))
    carpenter_workshops = _proven_carpenter_workshops(work)
    unchanged_order_wait_ticks = 0
    current_order_qty = order_qty_left
    if manager_orders > 0 and order_qty_left > 0 and carpenter_workshops > 0:
        for entry in reversed(action_history):
            actual_ticks = _to_int(entry.get("actual_ticks"))
            before_qty = entry.get("order_qty_left_before")
            after_qty = entry.get("order_qty_left_after")
            if (
                actual_ticks > 0
                and before_qty is not None
                and after_qty is not None
                and _to_int(before_qty) == current_order_qty
                and _to_int(after_qty) == current_order_qty
            ):
                unchanged_order_wait_ticks += actual_ticks
                continue
            if unchanged_order_wait_ticks:
                break

    queued_order_stuck = (
        manager_orders > 0
        and order_qty_left > 0
        and carpenter_workshops > 0
        and unchanged_order_wait_ticks >= 1000
    )
    do_not_repeat_wait = bool(
        queued_order_stuck or (tick_no_progress_streak >= 2 and no_progress_streak >= 3)
    )
    do_not_repeat_menu_path = bool(
        menu_no_progress_streak >= 6
        and (
            repeated_menu_family_count >= 3
            or repeated_key_fingerprint_count >= 3
            or agent_marked_bad_path
        )
    )
    sticky_blocked_menu_path = bool(
        no_progress_streak >= 6
        and (
            sticky_repeated_menu_family_count >= 4
            or sticky_repeated_key_fingerprint_count >= 4
            or sticky_agent_marked_bad_path
        )
    )
    if sticky_blocked_menu_path and not do_not_repeat_menu_path:
        repeated_menu_family = sticky_repeated_menu_family
        repeated_menu_family_count = sticky_repeated_menu_family_count
        repeated_key_fingerprint = sticky_repeated_key_fingerprint
        repeated_key_fingerprint_count = sticky_repeated_key_fingerprint_count
        agent_marked_bad_path = sticky_agent_marked_bad_path
        do_not_repeat_menu_path = True
    return {
        "last_productive_step": last_productive_step,
        "no_progress_streak": no_progress_streak,
        "tick_no_progress_streak": tick_no_progress_streak,
        "last_progress_kind": last_progress_kind,
        "queued_order_stuck": queued_order_stuck,
        "manager_order_qty_unchanged_after_ticks": unchanged_order_wait_ticks,
        "do_not_repeat_wait": do_not_repeat_wait,
        "menu_no_progress_streak": menu_no_progress_streak,
        "repeated_menu_family": repeated_menu_family,
        "repeated_menu_family_count": repeated_menu_family_count,
        "repeated_key_fingerprint": repeated_key_fingerprint,
        "repeated_key_fingerprint_count": repeated_key_fingerprint_count,
        "last_action_family": last_action_family,
        "last_key_fingerprint": last_key_fingerprint,
        "escape_recovery_attempted": escape_recovery_attempted,
        "agent_marked_bad_menu_path": agent_marked_bad_path,
        "sticky_blocked_menu_path": sticky_blocked_menu_path,
        "do_not_repeat_menu_path": do_not_repeat_menu_path,
    }


def encode_observation(
    state: Dict[str, Any],
    screen_text: Optional[str] = None,
    action_history: Optional[List[Dict[str, Any]]] = None,
    last_action_result: Optional[Dict[str, Any]] = None,
    previous_screen: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Return (text_summary, machine_state) tuple for a given environment state.

    Args:
        state: Game state dictionary
        screen_text: Optional screen text from CopyScreen (for keystroke mode)
        action_history: Optional list of recent actions (for keystroke mode memory)
        last_action_result: Optional result from previous action (for feedback)

    Returns:
        Tuple of (text observation for agent, cleaned state dict)
    """
    clean_state = redact_noise(state)

    time_tick = clean_state.get("time", 0)
    population = clean_state.get("population", 0)
    stocks = clean_state.get("stocks", {})
    risks = clean_state.get("risks", [])
    reminders = clean_state.get("reminders", [])
    pause_state = clean_state.get("pause_state", None)
    viewscreen_type = clean_state.get("viewscreen_type")
    survival = clean_state.get("survival") if isinstance(clean_state.get("survival"), dict) else {}
    work = clean_state.get("work") if isinstance(clean_state.get("work"), dict) else {}
    keystroke_history = [
        entry
        for entry in (action_history or [])
        if entry.get("action_type") in (None, "KEYSTROKE")
    ]
    recent_progress_summary = _recent_progress_summary(keystroke_history, work)
    if recent_progress_summary:
        clean_state["recent_progress_summary"] = recent_progress_summary
    ui_work = clean_state.get("ui_work") if isinstance(clean_state.get("ui_work"), dict) else {}
    ui_target_setup = (
        clean_state.get("ui_target_setup")
        if isinstance(clean_state.get("ui_target_setup"), dict)
        else {}
    )
    ui_work_feedback = (
        clean_state.get("ui_work_feedback")
        if isinstance(clean_state.get("ui_work_feedback"), dict)
        else {}
    )
    ui_run_progress = (
        clean_state.get("ui_run_progress")
        if isinstance(clean_state.get("ui_run_progress"), dict)
        else {}
    )
    ui_build_feedback = (
        clean_state.get("ui_build_feedback")
        if isinstance(clean_state.get("ui_build_feedback"), dict)
        else {}
    )
    ui_workshop_feedback = (
        clean_state.get("ui_workshop_feedback")
        if isinstance(clean_state.get("ui_workshop_feedback"), dict)
        else {}
    )
    screen_shows_blocked_placement = bool(
        screen_text
        and (
            "Blocked" in screen_text
            or "Building present" in screen_text
            or "Needs building material" in screen_text
        )
    )
    screen_shows_ready_workshop_placement = bool(
        screen_text
        and "Carpenter's Workshop" in screen_text
        and "Placement" in screen_text
        and "Enter: Place" in screen_text
        and not screen_shows_blocked_placement
    )
    screen_shows_workshop_material_selection = bool(
        screen_text
        and "Carpenter's Workshop" in screen_text
        and "Item" in screen_text
        and "Dist" in screen_text
        and "Num" in screen_text
        and "Enter: Select" in screen_text
        and "Needs building material" not in screen_text
    )
    screen_shows_workshop_select_state = bool(
        screen_shows_ready_workshop_placement or screen_shows_workshop_material_selection
    )
    screen_lower = screen_text.lower() if screen_text else ""
    screen_shows_manager_required = "manager is required" in screen_lower
    screen_shows_production_cancellation = bool(
        "cancels" in screen_lower
        and (
            "construct bed" in screen_lower
            or "bed" in screen_lower
            or "needs" in screen_lower
            or "nee[" in screen_lower
        )
    )
    screen_shows_pending_workshop_construction = bool(
        "carpenter's workshop" in screen_lower
        and (
            "waiting for construction" in screen_lower
            or "construction inactive" in screen_lower
            or "s: suspend construction" in screen_lower
        )
    )
    screen_state = _classify_screen_state(screen_text)
    if screen_state:
        clean_state["screen_state"] = screen_state
    active_material_blocked = bool(
        ui_build_feedback.get("material_blocked") and not screen_shows_workshop_select_state
    )

    # Build status section
    status_lines = []

    if screen_state:
        screen_line = (
            "Screen state: "
            f"mode={screen_state.get('mode')}, "
            f"confidence={screen_state.get('confidence')}"
        )
        highlighted = screen_state.get("highlighted")
        if highlighted:
            screen_line += f", highlighted={highlighted}"
        evidence = screen_state.get("evidence")
        if isinstance(evidence, list) and evidence:
            screen_line += "; evidence=" + " | ".join(str(item) for item in evidence[:3])
        status_lines.append(screen_line)
        instruction = screen_state.get("instruction")
        if instruction:
            status_lines.append(f"Screen instruction: {instruction}")

    # Game state feedback (critical for agent to know if game is running)
    if pause_state is True:
        status_lines.append("Game Status: PAUSED (press SPACE to unpause)")
    elif pause_state is False:
        status_lines.append("Game Status: RUNNING")
    if isinstance(viewscreen_type, str) and viewscreen_type:
        status_lines.append(f"DF Viewscreen: {viewscreen_type}")
    if survival:
        status_lines.append(
            "Run resource flow: "
            f"food produced={survival.get('food_produced_in_run')}, "
            f"consumed={survival.get('food_consumed_in_run')}; "
            f"drink produced={survival.get('drink_produced_in_run')}, "
            f"consumed={survival.get('drink_consumed_in_run')}; "
            f"evidence_complete={survival.get('flow_evidence_complete')}"
        )
        death_records = survival.get("death_records")
        status_lines.append(
            "Run death evidence: "
            f"records={len(death_records) if isinstance(death_records, list) else 'unknown'}, "
            f"causes_known={survival.get('death_causes_known')}, "
            f"neglect_deaths={survival.get('neglect_deaths')}"
        )

    # Last action result feedback
    if last_action_result is not None:
        last_action = last_action_result.get("_action")
        if isinstance(last_action, dict):
            status_lines.append(
                "Last Action command: "
                + _format_last_action_command(last_action_result.get("_action_step", "?"), last_action)
            )
        accepted = last_action_result.get("accepted", last_action_result.get("ok", True))
        action_result = (
            last_action_result.get("result")
            if isinstance(last_action_result.get("result"), dict)
            else {}
        )
        if accepted:
            status_lines.append("Last Action: ACCEPTED")
        else:
            result_error = action_result.get("error")
            reason = (
                last_action_result.get("reason")
                or last_action_result.get("why")
                or last_action_result.get("error")
                or result_error
                or "unknown"
            )
            if action_result.get("partial") and (_int_or_none(action_result.get("placed_count")) or 0) > 0:
                status_lines.append(f"Last Action: PARTIAL MUTATION - {reason}")
            else:
                status_lines.append(f"Last Action: REJECTED - {reason}")
        if action_result:
            placed_tiles = action_result.get("placed")
            if isinstance(placed_tiles, list) and placed_tiles:
                tile_parts = []
                for entry in placed_tiles:
                    if not isinstance(entry, dict):
                        continue
                    coords = _int_list_or_none(
                        [entry.get("x"), entry.get("y"), entry.get("z")], 3
                    )
                    if coords:
                        tile_parts.append(f"({coords[0]},{coords[1]},{coords[2]})")
                if tile_parts:
                    status_lines.append("Placed tiles: " + ", ".join(tile_parts))
            failed_tiles = action_result.get("failed")
            if isinstance(failed_tiles, list) and failed_tiles:
                tile_parts = []
                for entry in failed_tiles:
                    if not isinstance(entry, dict):
                        continue
                    fx = _int_or_none(entry.get("x"))
                    fy = _int_or_none(entry.get("y"))
                    fz = _int_or_none(entry.get("z"))
                    err = entry.get("error")
                    if fx is not None and fy is not None and err:
                        facts = [
                            f"{key}={entry[key]}"
                            for key in ("tile_shape", "tiletype")
                            if entry.get(key) is not None
                        ]
                        suffix = " [" + ", ".join(facts) + "]" if facts else ""
                        coords = f"({fx},{fy},{fz})" if fz is not None else f"({fx},{fy})"
                        tile_parts.append(f"{coords}: {err}{suffix}")
                if tile_parts:
                    status_lines.append("Failed tiles: " + "; ".join(tile_parts))
            detail_parts = []
            for key in (
                "newly_designated",
                "already_designated",
                "non_wall_tiles",
                "placed_count",
                "failed_count",
                "created_job_ids",
                "building_id",
                "unsuspended",
                "suspended_found",
                "before_workshops_of_kind",
                "after_workshops_of_kind",
                "before_farm_plots",
                "after_farm_plots",
                "shrubs_designated",
                "non_shrub_tiles",
                "seasons_changed",
                "seeds_on_hand",
                "before_plant_id",
                "after_plant_id",
            ):
                if key not in action_result:
                    continue
                value = action_result[key]
                if isinstance(value, list):
                    int_list = _int_list_or_none(value, len(value))
                    if not int_list:
                        continue
                    detail_parts.append(f"{key}={_render_int_list(int_list)}")
                else:
                    parsed = _int_or_none(value)
                    if parsed is None:
                        continue
                    detail_parts.append(f"{key}={parsed}")
            if detail_parts:
                detail_line = "Last Action detail: " + ", ".join(detail_parts)
                status_lines.append(detail_line[:120])

            # LABOR result carries boolean before/after enabled state; render it
            # explicitly (a no-op flip shows before==after, changed=False).
            if "labor_changed" in action_result:
                labor_unit = _int_or_none(action_result.get("unit_id"))
                labor_name = action_result.get("labor")
                before = action_result.get("labor_before")
                after = action_result.get("labor_after")
                if labor_unit is not None and isinstance(labor_name, str):
                    labor_detail = (
                        f"Last Action LABOR: #{labor_unit} {labor_name} "
                        f"before={bool(before)} after={bool(after)} "
                        f"changed={bool(action_result.get('labor_changed'))}"
                    )
                    status_lines.append(labor_detail[:120])
            # FARM outcome: seasons_set (list of season names) and
            # seasons_skipped (list of {season, reason}) are string/dict shaped,
            # so the int-only whitelist above cannot render them. Surface them
            # explicitly so a partially-skipped crop selection tells the agent
            # which seasons took and which were skipped, and why.
            seasons_set = action_result.get("seasons_set")
            if isinstance(seasons_set, list) and seasons_set:
                set_names = [
                    _sanitize_token(name) for name in seasons_set if isinstance(name, str) and name
                ]
                set_names = [n for n in set_names if n]
                if set_names:
                    status_lines.append("FARM crops set: " + ",".join(set_names[:4]))
            seasons_skipped = action_result.get("seasons_skipped")
            if isinstance(seasons_skipped, list) and seasons_skipped:
                skip_parts = []
                for entry in seasons_skipped[:4]:
                    if not isinstance(entry, dict):
                        continue
                    season = entry.get("season")
                    reason = entry.get("reason")
                    if isinstance(season, str) and season:
                        label = _sanitize_token(season)
                        if isinstance(reason, str) and reason:
                            label += f" ({_sanitize_token(reason)})"
                        if label:
                            skip_parts.append(label)
                if skip_parts:
                    status_lines.append("FARM seasons skipped: " + "; ".join(skip_parts))

    # Screen change feedback - critical for agent to know if actions had effect
    if screen_text and previous_screen:
        diff = _compute_screen_diff(previous_screen, screen_text)
        if diff.get("has_prev"):
            if diff.get("screen_identical"):
                status_lines.append(
                    "⚠️ WARNING: Screen UNCHANGED - your action may have had NO EFFECT!"
                )
                status_lines.append("   Try a DIFFERENT approach or key sequence.")
            elif not diff.get("cursor_moved") and diff.get("change_pct", 100) < 10:
                status_lines.append("⚠️ NOTICE: Cursor did NOT move. Screen barely changed.")
                status_lines.append("   Your navigation keys may not be working as expected.")
            elif diff.get("cursor_moved"):
                prev_pos = diff.get("prev_cursor")
                curr_pos = diff.get("curr_cursor")
                if prev_pos and curr_pos:
                    dy = curr_pos[0] - prev_pos[0]
                    dx = curr_pos[1] - prev_pos[1]
                    direction = []
                    if dy < 0:
                        direction.append(f"up {-dy}")
                    elif dy > 0:
                        direction.append(f"down {dy}")
                    if dx < 0:
                        direction.append(f"left {-dx}")
                    elif dx > 0:
                        direction.append(f"right {dx}")
                    if direction:
                        status_lines.append(f"Cursor moved: {', '.join(direction)} tiles")

    def _stock_with_usable(label: str, total_key: str, usable_key: str) -> str:
        total = stocks.get(total_key, 0)
        usable = stocks.get(usable_key)
        if usable is None or usable == total:
            return f"{label}: {total}"
        # locked = claimed by queued jobs or already inside (pending)
        # buildings/constructions — a new BUILD cannot consume those items
        return f"{label}: {total} ({usable} usable, rest locked in jobs/buildings)"

    status_lines.extend(
        [
            f"Time: tick {time_tick}",
            f"Population: {population} dwarves",
            (
                f"Food: {stocks.get('food', 0)}, Drink: {stocks.get('drink', 0)}, "
                f"{_stock_with_usable('Wood', 'wood', 'wood_usable')}, "
                f"{_stock_with_usable('Stone', 'stone', 'stone_usable')}"
            ),
        ]
    )
    if work:
        build_site = _int_list_or_none(work.get("carpenter_build_site"), 3)
        if build_site is not None:
            x, y, z = build_site
            status_lines.append(
                f"Workshop site candidate observed: carpenter_build_site=({x},{y},{z}) "
                "— 3x3 open floor there."
            )
        else:
            status_lines.append(
                "No 3x3 workshop site observed yet. CarpenterWorkshop needs a "
                "full 3x3 footprint of open floor near your fort; dig out or "
                "clear more contiguous floor space first."
            )
        if work.get("cursor_z") is not None or work.get("window_z") is not None:
            cursor_x = work.get("cursor_x")
            cursor_label = "inactive" if _is_inactive_df_cursor(cursor_x) else "active"
            status_lines.append(
                "Live view: "
                f"cursor_{cursor_label}=({work.get('cursor_x', '?')},{work.get('cursor_y', '?')},"
                f"{work.get('cursor_z', '?')}), "
                f"window=({work.get('window_x', '?')},{work.get('window_y', '?')},"
                f"{work.get('window_z', '?')})"
            )
            if cursor_label == "inactive":
                status_lines.append(
                    "Live view note: cursor -30000 means no active DF cursor is "
                    "currently exposed on this screen; opening a designation, "
                    "stockpile, or building-placement mode can create a normal "
                    "cursor again."
                )
        planned_workshops = _work_int(
            work,
            "carpenter_workshops_planned",
            default=_work_int(work, "carpenter_workshops"),
        )
        usable_workshops = _proven_carpenter_workshops(work)
        unproven_workshops = _work_int(
            work,
            "carpenter_workshops_unproven",
            default=max(0, planned_workshops - usable_workshops),
        )
        status_lines.append(
            "Utility work: "
            f"manager_orders={work.get('manager_orders_count', 0)}, "
            f"order_qty_left={work.get('manager_orders_amount_left', 0)}, "
            f"carpenter_workshops={work.get('carpenter_workshops', 0)}, "
            f"planned_workshops={planned_workshops}, "
            f"usable_workshops={usable_workshops}, "
            f"unproven_workshops={unproven_workshops}, "
            f"workshop_task_jobs={work.get('carpenter_workshop_task_jobs', 0)}, "
            "workshop_construction_jobs="
            f"{work.get('carpenter_workshop_construction_jobs', 0)}, "
            f"active_jobs={work.get('active_jobs', 0)}, "
            f"active_carpenter_jobs={work.get('active_carpenter_jobs', 0)}, "
            f"carpenter_labors={work.get('carpenter_labors_enabled', 0)}"
        )
        task_job_names = work.get("carpenter_workshop_task_job_type_names")
        if isinstance(task_job_names, list) and task_job_names:
            status_lines.append(
                "Workshop queued tasks: " + ", ".join(str(name) for name in task_job_names[:8])
            )
        active_job_names = work.get("active_job_type_names")
        if isinstance(active_job_names, list) and active_job_names:
            status_lines.append(
                "Active jobs: " + ", ".join(str(name) for name in active_job_names[:8])
            )
        workshop_rect_values = [
            _int_or_none(work.get(key))
            for key in (
                "carpenter_workshop_x1",
                "carpenter_workshop_y1",
                "carpenter_workshop_z",
                "carpenter_workshop_x2",
                "carpenter_workshop_y2",
            )
        ]
        if all(value is not None for value in workshop_rect_values):
            x1, y1, z, x2, y2 = workshop_rect_values
            status_lines.append(
                "Existing workshop: "
                f"rect=({x1},{y1},{z})-({x2},{y2},{z}); use this as "
                "world-state evidence for reselecting the placed workshop, "
                "not as score proof."
            )
        if planned_workshops > 0 and usable_workshops <= 0:
            status_lines.append(
                "Workshop proof: a carpenter workshop object is placed/planned, "
                "but no usable workshop or task job is proven yet. Do not treat "
                "carpenter_workshops/planned_workshops as production progress."
            )
            if (
                _work_int(work, "carpenter_workshop_construction_jobs") > 0
                or _work_int(work, "active_construct_building_jobs") > 0
            ):
                status_lines.append(
                    "Workshop construction route: a construction job is already "
                    "queued for the placed workshop. Do not start a new starter, "
                    "material, D_BUILDING, D_NOBLES, or manager route. If a menu "
                    "is visible, first submit only LEAVESCREEN with "
                    "advance_ticks=0. Once the main map is visible, submit an "
                    "empty-key KEYSTROKE with advance_ticks >= 1000 so the "
                    "carpenter can build it. If that still leaves usable_workshops=0, "
                    "inspect the existing workshop or jobs screen with visible "
                    "evidence instead of placing another workshop."
                )
            if (
                _work_int(work, "carpenter_workshop_construction_jobs") <= 0
                and _work_int(work, "active_construct_building_jobs") <= 0
                and _work_int(work, "carpenter_workshop_task_jobs") <= 0
            ):
                status_lines.append(
                    "Workshop proof route: before using manager/nobles or waiting, "
                    "return to a verified main-map screen and reselect the existing "
                    "workshop with the existing_workshop target. If the selected "
                    "workshop screen is usable, open BUILDJOB_ADD; if it still says "
                    "Waiting for construction or Needs Carpentry, diagnose that "
                    "visible blocker instead of placing another workshop."
                )
        elif work.get("carpenter_workshops_usable_carried_forward"):
            status_lines.append(
                "Workshop proof: this workshop was already proven usable by "
                "earlier real task-menu evidence in this run. Do not reopen the "
                "same workshop just to prove usability again; either let queued "
                "work run, inspect visible cancellation text, or choose a new "
                "productive branch."
            )
        if (
            int(work.get("manager_orders_count") or 0) > 0
            and int(work.get("manager_orders_amount_left") or 0) > 0
            and usable_workshops > 0
        ):
            production_note = (
                "Live UI production phase: a real manager order is queued and "
                "a usable/task-proven carpenter workshop exists."
            )
            if screen_shows_manager_required:
                production_note += (
                    " The visible screen says a manager is required; appoint a "
                    "manager before relying on time advancement."
                )
            elif screen_shows_production_cancellation:
                production_note += (
                    " A visible production cancellation/Needs message is present; "
                    "do not blindly wait or switch to unrelated dig/stockpile work. "
                    "Inspect the carpenter workshop/task list or cancellation "
                    "reason, then fix the shown production blocker."
                )
            else:
                production_note += (
                    " If you are in a menu, use LEAVESCREEN to return to the main "
                    "map; from the main map, advance_ticks >= 1000 so dwarves can "
                    "work the order. If a large advance leaves order_qty_left "
                    "unchanged, inspect the workshop/task/cancellation path before "
                    "changing objectives."
                )
            status_lines.append(production_note)
        elif (
            int(work.get("carpenter_workshop_task_jobs") or 0) > 0
            and usable_workshops > 0
            and int(work.get("manager_orders_count") or 0) <= 0
        ):
            task_note = (
                "Live UI workshop task phase: a real carpenter workshop task is "
                "queued on a usable workshop. Keep the existing_workshop target "
                "anchored to the placed workshop; do not switch to starter "
                "digging, fresh D_BUILDING placement, D_NOBLES, or manager orders "
                "until this queued task either starts, completes, or shows a "
                "visible cancellation/blocker."
            )
            if int(work.get("active_carpenter_jobs") or 0) <= 0:
                task_note += (
                    " No active carpenter job is currently proven, so from the "
                    "main map prefer a larger empty-key time advance or inspect "
                    "D_JOBLIST/cancellation evidence before adding more tasks."
                )
            status_lines.append(task_note)
        elif (
            int(work.get("manager_orders_count") or 0) > 0
            and int(work.get("manager_orders_amount_left") or 0) > 0
            and planned_workshops > 0
            and usable_workshops <= 0
        ):
            status_lines.append(
                "Live UI production blocker: a production order may exist and a "
                "workshop object is placed, but the workshop is not usable/task-"
                "proven. Solve the construction or task-menu blocker before "
                "waiting for production."
            )
    crew = clean_state.get("crew")
    if isinstance(crew, dict) and crew.get("ok"):
        citizens = crew.get("citizens") if isinstance(crew.get("citizens"), dict) else {}
        if isinstance(citizens, dict) and citizens:
            total = _int_or_none(citizens.get("total"))
            idle = _int_or_none(citizens.get("idle"))
            if total is not None and idle is not None:
                labor_parts = []
                for label, key in (
                    ("mining", "mining_labor"),
                    ("carpentry", "carpentry_labor"),
                    ("woodcutting", "woodcutting_labor"),
                    ("masonry", "masonry_labor"),
                    ("herbalism", "herbalism_labor"),
                ):
                    labor_value = _int_or_none(citizens.get(key))
                    if labor_value is not None:
                        labor_parts.append(f"{label}={labor_value}")
                crew_line = f"Crew: {total} citizens, {idle} idle"
                if labor_parts:
                    crew_line += "; labors: " + ", ".join(labor_parts)
                status_lines.append(crew_line)

            # Per-citizen detail: id -> enabled whitelist labors + current job.
            # The LABOR action targets a unit by id, so the agent needs this
            # mapping to choose whom to reassign (e.g. flip brewing on an idle
            # citizen so a starved brew job gets taken).
            citizen_list = citizens.get("list")
            if isinstance(citizen_list, list) and citizen_list:
                citizen_parts = []
                for entry in citizen_list[:20]:
                    if not isinstance(entry, dict):
                        continue
                    cid = _int_or_none(entry.get("id"))
                    if cid is None:
                        continue
                    labors = entry.get("labors")
                    if isinstance(labors, list):
                        labor_names = [str(name) for name in labors if isinstance(name, str)]
                    else:
                        labor_names = []
                    labor_str = ",".join(labor_names) if labor_names else "-"
                    job = entry.get("current_job_type")
                    job_str = str(job) if isinstance(job, str) and job else "idle"
                    citizen_parts.append(f"#{cid} [{labor_str}] {job_str}")
                if citizen_parts:
                    status_lines.append("Citizens: " + "; ".join(citizen_parts))

        jobs = crew.get("jobs") if isinstance(crew.get("jobs"), dict) else {}
        jobs_construct_building = None
        if isinstance(jobs, dict) and jobs:
            jobs_total = _int_or_none(jobs.get("total"))
            jobs_dig = _int_or_none(jobs.get("dig"))
            jobs_construct_building = _int_or_none(jobs.get("construct_building"))
            jobs_workshop_task = _int_or_none(jobs.get("workshop_task"))
            jobs_suspended = _int_or_none(jobs.get("suspended"))
            if all(
                value is not None
                for value in (
                    jobs_total,
                    jobs_dig,
                    jobs_construct_building,
                    jobs_workshop_task,
                    jobs_suspended,
                )
            ):
                jobs_line = (
                    f"Jobs: total={jobs_total} (dig={jobs_dig}, "
                    f"construct_building={jobs_construct_building}, "
                    f"workshop_tasks={jobs_workshop_task}, suspended={jobs_suspended})"
                )
                haul_connected = _int_or_none(
                    jobs.get("construct_building_walk_group_connected")
                )
                haul_disconnected = _int_or_none(
                    jobs.get("construct_building_walk_group_disconnected")
                )
                haul_unknown = _int_or_none(
                    jobs.get("construct_building_walk_group_unknown")
                )
                if all(
                    value is not None
                    for value in (haul_connected, haul_disconnected, haul_unknown)
                ):
                    jobs_line += (
                        "; construction walk groups: "
                        f"connected={haul_connected}, disconnected={haul_disconnected}, "
                        f"unknown={haul_unknown}"
                    )
                entries = jobs.get("entries")
                if isinstance(entries, list) and entries:
                    sample_parts = []
                    for entry in entries[:3]:
                        if not isinstance(entry, dict):
                            continue
                        entry_pos = _int_list_or_none(entry.get("pos"), 3)
                        if entry_pos is None:
                            continue
                        entry_type = entry.get("type", "?")
                        x, y, z = entry_pos
                        sample = f"{entry_type}@({x},{y},{z})"
                        if entry.get("suspended"):
                            sample += "[suspended]"
                        if entry.get("has_worker") is False:
                            sample += "[unassigned]"
                        walk_group_connectivity = entry.get("walk_group_connectivity")
                        if (
                            isinstance(walk_group_connectivity, str)
                            and walk_group_connectivity
                        ):
                            sample += (
                                "[walk_group_connectivity="
                                f"{walk_group_connectivity}]"
                            )
                        sample_parts.append(sample)
                    if sample_parts:
                        jobs_line += "; sample: " + ", ".join(sample_parts)
                status_lines.append(jobs_line)

        workshops = crew.get("workshops")
        if isinstance(workshops, list) and workshops:
            for workshop in workshops[:5]:
                if not isinstance(workshop, dict):
                    continue
                workshop_pos = _int_list_or_none(workshop.get("pos"), 3)
                if workshop_pos is None:
                    continue
                workshop_id = _int_or_none(workshop.get("id"))
                stage = _int_or_none(workshop.get("stage"))
                max_stage = _int_or_none(workshop.get("max_stage"))
                queued_jobs = _int_or_none(workshop.get("queued_jobs"))
                if None in (workshop_id, stage, max_stage, queued_jobs):
                    continue
                subtype = workshop.get("subtype", "?")
                x, y, z = workshop_pos
                built = bool(workshop.get("built")) or stage >= max_stage
                if built:
                    workshop_line = (
                        f"Workshop id={workshop_id} {subtype} at ({x},{y},{z}): "
                        f"construction COMPLETE (stage {stage}/{max_stage}), "
                        f"queued_jobs={queued_jobs}"
                    )
                    if subtype == "Carpenters":
                        workshop_line += " — ORDER can queue jobs to any built carpenter workshop."
                    elif subtype == "Still":
                        workshop_line += (
                            " — ORDER job=brew can queue brewing jobs at any built Still."
                        )
                else:
                    workshop_line = (
                        f"Workshop id={workshop_id} {subtype} at ({x},{y},{z}): "
                        f"UNDER CONSTRUCTION (stage {stage}/{max_stage}), "
                        f"queued_jobs={queued_jobs}"
                    )
                    if jobs_construct_building == 0:
                        workshop_line += " — no construct job exists; construction is stalled"
                status_lines.append(workshop_line)

        placed = crew.get("placed_furniture")
        if isinstance(placed, dict) and placed:
            placed_parts = []
            for key in ("bed", "door", "table", "chair"):
                value = _int_or_none(placed.get(key))
                if value is not None:
                    placed_parts.append(f"{key}s={value}")
            if placed_parts:
                status_lines.append("Placed furniture buildings: " + ", ".join(placed_parts))
            positions = crew.get("placed_furniture_positions")
            if isinstance(positions, dict) and positions:
                position_parts = []
                for key in ("bed", "door", "table", "chair"):
                    coords = positions.get(key)
                    if not isinstance(coords, list) or not coords:
                        continue
                    rendered = []
                    for coord in coords[:8]:
                        if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                            cx = _int_or_none(coord[0])
                            cy = _int_or_none(coord[1])
                            if cx is not None and cy is not None:
                                rendered.append(f"({cx},{cy})")
                    if rendered:
                        position_parts.append(f"{key}s at " + ",".join(rendered))
                if position_parts:
                    status_lines.append(
                        "Furniture positions: "
                        + "; ".join(position_parts)
                        + " — construction cannot be placed on occupied tiles."
                    )

        farm_plots = _int_or_none(crew.get("farm_plots"))
        if farm_plots is not None:
            farm_plots_line = f"Farm plots built: {farm_plots}"
            farm_plot_positions = crew.get("farm_plot_positions")
            if isinstance(farm_plot_positions, list) and farm_plot_positions:
                rendered = []
                for coord in farm_plot_positions[:8]:
                    if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                        cx = _int_or_none(coord[0])
                        cy = _int_or_none(coord[1])
                        if cx is not None and cy is not None:
                            rendered.append(f"({cx},{cy})")
                if rendered:
                    farm_plots_line += " at " + ",".join(rendered)
            status_lines.append(farm_plots_line)

        farm_plot_details = crew.get("farm_plot_details")
        if isinstance(farm_plot_details, list) and farm_plot_details:
            season_labels = ("spring", "summer", "autumn", "winter")
            for detail in farm_plot_details[:8]:
                if not isinstance(detail, dict):
                    continue
                plot_id = _int_or_none(detail.get("id"))
                if plot_id is None:
                    continue
                rect = detail.get("rect")
                loc = ""
                if isinstance(rect, (list, tuple)) and len(rect) >= 5:
                    coords = [_int_or_none(v) for v in rect[:5]]
                    if all(v is not None for v in coords):
                        x1, y1, x2, y2, zz = coords
                        loc = f" ({x1},{y1}..{x2},{y2} z{zz}"
                        if detail.get("built"):
                            loc += ", built)"
                        else:
                            stage = _int_or_none(detail.get("stage")) or 0
                            max_stage = _int_or_none(detail.get("max_stage")) or 0
                            loc += f", stage {stage}/{max_stage})"
                crops = detail.get("crops")
                crop_parts = []
                if isinstance(crops, list):
                    for idx, label in enumerate(season_labels):
                        value = crops[idx] if idx < len(crops) else None
                        token = value if isinstance(value, str) and value else "-"
                        crop_parts.append(f"{label}={token}")
                line = f"Farm plot #{plot_id}{loc}"
                if crop_parts:
                    line += " crops " + " ".join(crop_parts)
                status_lines.append(line)

        seeds = crew.get("seeds")
        if isinstance(seeds, list) and seeds:
            seed_parts = []
            for entry in seeds[:12]:
                if not isinstance(entry, dict):
                    continue
                token = entry.get("token")
                count = _int_or_none(entry.get("count"))
                if not isinstance(token, str) or not token or count is None:
                    continue
                where = "surface" if entry.get("surface") else "subterranean"
                seasons = entry.get("seasons")
                if isinstance(seasons, list) and seasons:
                    season_str = "all" if len(seasons) >= 4 else "/".join(str(s) for s in seasons)
                else:
                    season_str = "none"
                seed_parts.append(f"{token} x{count} ({where}, {season_str})")
            if seed_parts:
                status_lines.append("Seeds on hand: " + ", ".join(seed_parts))

        current_season = crew.get("current_season")
        if isinstance(current_season, str) and current_season:
            status_lines.append(f"Season: {current_season}")

        goods = crew.get("goods")
        if isinstance(goods, dict) and goods:
            goods_parts = []
            for key in ("bed", "door", "table", "chair", "barrel", "bin", "wood"):
                value = _int_or_none(goods.get(key))
                if value is not None:
                    label = "wood_logs" if key == "wood" else f"{key}s"
                    goods_parts.append(f"{label}={value}")
            if goods_parts:
                status_lines.append("Finished goods in play: " + ", ".join(goods_parts))

        rect_tiles = crew.get("rect_tiles")
        if isinstance(rect_tiles, dict) and rect_tiles:
            wall = _int_or_none(rect_tiles.get("wall"))
            tree = _int_or_none(rect_tiles.get("tree"))
            floor = _int_or_none(rect_tiles.get("floor"))
            shrub = _int_or_none(rect_tiles.get("shrub"))
            shrub_or_other = _int_or_none(rect_tiles.get("shrub_or_other"))
            designated = _int_or_none(rect_tiles.get("designated"))
            if all(value is not None for value in (wall, floor, shrub_or_other, designated)):
                tree_part = (
                    f"tree_trunks={tree} (fell with DIG kind=chop for logs), "
                    if tree is not None
                    else ""
                )
                if shrub is not None:
                    other = shrub_or_other - shrub
                    shrub_part = f"shrubs={shrub} (gatherable with DIG kind=gather), other={other}"
                else:
                    shrub_part = f"shrub/other={shrub_or_other}"
                status_lines.append(
                    f"Fort-area tiles: wall={wall} (diggable), {tree_part}"
                    f"floor={floor}, "
                    f"{shrub_part} (this harness only designates WALL tiles for "
                    "dig/channel; other tiles in the rect are left untouched), "
                    f"designated={designated}"
                )

    fort = clean_state.get("fort")
    if isinstance(fort, dict) and fort.get("ok"):
        enclosed_spaces = _int_or_none(fort.get("enclosed_spaces"))
        functional_rooms = _int_or_none(fort.get("functional_rooms"))
        constructions = _int_or_none(fort.get("constructions"))
        if None not in (enclosed_spaces, functional_rooms, constructions):
            structure_line = (
                "Fort structure (plan-agnostic): "
                f"enclosed_spaces={enclosed_spaces}, "
                f"functional_rooms={functional_rooms}, "
                f"constructions={constructions}"
            )
            pending = _int_or_none(fort.get("pending_constructions"))
            if pending is not None:
                structure_line += f", queued_constructions={pending} (ordered, not built yet)"
            status_lines.append(structure_line)

        spaces = fort.get("spaces")
        if isinstance(spaces, list) and spaces:
            room_parts = []
            for space in spaces[:6]:
                if not isinstance(space, dict):
                    continue
                kind = space.get("kind")
                tiles = _int_or_none(space.get("tiles"))
                z = _int_or_none(space.get("z"))
                if not kind or tiles is None or z is None:
                    continue
                room_parts.append(f"{kind}({tiles} tiles, z{z})")
            if room_parts:
                status_lines.append("Rooms: " + ", ".join(room_parts))

        nearby_trees = fort.get("nearby_trees")
        if isinstance(nearby_trees, dict):
            tree_total = _int_or_none(nearby_trees.get("total"))
            clusters = nearby_trees.get("clusters")
            if tree_total is not None:
                if tree_total > 0 and isinstance(clusters, list) and clusters:
                    parts = []
                    for cluster in clusters[:3]:
                        if not isinstance(cluster, dict):
                            continue
                        count = _int_or_none(cluster.get("count"))
                        cl_x = _int_or_none(cluster.get("x"))
                        cl_y = _int_or_none(cluster.get("y"))
                        cl_z = _int_or_none(cluster.get("z"))
                        if None in (count, cl_x, cl_y, cl_z):
                            continue
                        parts.append(f"{count} trunks near ({cl_x},{cl_y},{cl_z})")
                    if parts:
                        status_lines.append(
                            "Nearby trees (within 40 tiles of the citizens, "
                            "possibly beyond the minimap): " + "; ".join(parts)
                        )
                else:
                    status_lines.append(
                        "Nearby trees: none within 40 tiles of the citizens — "
                        "wood must come from farther away."
                    )

        construction_tiles = fort.get("construction_tiles")
        if isinstance(construction_tiles, list) and construction_tiles:
            by_row: Dict[tuple, List[int]] = {}
            for tile in construction_tiles:
                if not isinstance(tile, (list, tuple)) or len(tile) < 3:
                    continue
                x = _int_or_none(tile[0])
                y = _int_or_none(tile[1])
                z = _int_or_none(tile[2])
                if x is None or y is None or z is None:
                    continue
                by_row.setdefault((z, y), []).append(x)
            row_parts = []
            for (z, y), xs in sorted(by_row.items()):
                xs = sorted(set(xs))
                runs = []
                start = prev = xs[0]
                for value in xs[1:]:
                    if value == prev + 1:
                        prev = value
                        continue
                    runs.append((start, prev))
                    start = prev = value
                runs.append((start, prev))
                run_text = ",".join(f"x{a}" if a == b else f"x{a}-{b}" for a, b in runs)
                row_parts.append(f"z{z} y{y}: {run_text}")
                if len(row_parts) >= 12:
                    break
            if row_parts:
                status_lines.append("Wall/floor layout: " + "; ".join(row_parts))

        map_rows = fort.get("map_rows")
        map_origin = fort.get("map_origin")
        if (
            isinstance(map_rows, list)
            and map_rows
            and isinstance(map_origin, (list, tuple))
            and len(map_origin) >= 3
        ):
            ox = _int_or_none(map_origin[0])
            oy = _int_or_none(map_origin[1])
            oz = _int_or_none(map_origin[2])
            if ox is not None and oy is not None and oz is not None:
                rows = [str(row) for row in map_rows[:34]]
                width = max((len(row) for row in rows), default=0)
                status_lines.append(
                    f"Fort minimap (z={oz}; top-left tile is x={ox},y={oy}; "
                    "x increases rightward, y increases downward). Legend: "
                    "W=your wall, x=your QUEUED wall/floor (ordered, a dwarf "
                    "is still building it), #=natural wall, T=tree trunk, "
                    "b=bed, t=table, c=chair, d=door, w=workshop, .=floor, "
                    ",=shrub/boulder, @=dwarf, ~=impassable:"
                )
                ruler = "".join(str((ox + i) % 10) for i in range(width))
                status_lines.append(f"      {ruler}")
                for index, row in enumerate(rows):
                    status_lines.append(f"y={oy + index:>3}|{row}")
                status_lines.append(
                    "A room is enclosed only if every tile of its border is "
                    "W/#/T/w/d — trace the ring on the minimap and wall any "
                    "'.' or ',' gaps. An 'x' is already ordered: do NOT "
                    "re-place a wall there — advance time and it becomes W."
                )

        if enclosed_spaces == 0:
            status_lines.append(
                "No enclosed rooms yet — spaces count as rooms only when fully "
                "bounded by walls, buildings, or doors. BUILD kind=Wall can "
                "enclose them; check the Wall/floor layout line for gaps in "
                "your own walls."
            )

    if ui_work:
        status_lines.append(
            "Live UI target: "
            f"z={ui_work.get('target_z', '?')}, "
            f"designations={ui_work.get('target_dig_designations', 0)}, "
            f"floors={ui_work.get('target_floor_tiles', 0)}, "
            f"walls={ui_work.get('target_wall_tiles', 0)}"
        )
    if ui_work_feedback:
        if ui_work_feedback.get("target_refreshed"):
            status_lines.append(
                "Live UI feedback: target refreshed after repeated no-progress actions; "
                "use the fresh recommended keys once."
            )
        elif ui_work_feedback.get("target_refresh_failed"):
            status_lines.append(
                "Live UI feedback: target refresh failed; avoid repeating the same stale keys."
            )
        else:
            progress_delta = ui_work_feedback.get("last_ui_work_progress_delta", 0)
            excavation_delta = ui_work_feedback.get("last_ui_excavation_delta", 0)
            material_delta = ui_work_feedback.get("last_ui_material_delta", 0)
            no_progress_streak = ui_work_feedback.get("no_progress_streak", 0)
            status_lines.append(
                "Live UI feedback: "
                f"last_action_work_delta={progress_delta}, "
                f"last_action_excavation_delta={excavation_delta}, "
                f"last_action_material_delta={material_delta}, "
                f"no_progress_streak={no_progress_streak}"
            )
            if progress_delta or material_delta:
                if material_delta:
                    status_lines.append(
                        "Live UI feedback: the last action changed real material stocks."
                    )
                elif ui_work_feedback.get("target_step_succeeded") is False:
                    status_lines.append(
                        "Live UI feedback: the last action changed tracked tiles, "
                        "but the current material target did not acquire usable "
                        "wood or stone yet."
                    )
                else:
                    status_lines.append("Live UI feedback: the last action dug real tiles.")
            elif no_progress_streak:
                status_lines.append(
                    "Live UI feedback: the last action changed no tracked tiles; "
                    "do not repeat the same key sequence unless a fresh target is shown."
                )
    if recent_progress_summary:
        status_lines.append(
            "Recent progress summary: "
            f"last_productive_step={recent_progress_summary.get('last_productive_step')}, "
            f"no_progress_streak={recent_progress_summary.get('no_progress_streak')}, "
            f"tick_no_progress_streak={recent_progress_summary.get('tick_no_progress_streak')}, "
            f"last_progress_kind={recent_progress_summary.get('last_progress_kind')}, "
            f"queued_order_stuck={str(recent_progress_summary.get('queued_order_stuck')).lower()}, "
            "manager_order_qty_unchanged_after_ticks="
            f"{recent_progress_summary.get('manager_order_qty_unchanged_after_ticks')}, "
            f"do_not_repeat_wait={str(recent_progress_summary.get('do_not_repeat_wait')).lower()}, "
            f"menu_no_progress_streak={recent_progress_summary.get('menu_no_progress_streak')}, "
            f"repeated_menu_family={recent_progress_summary.get('repeated_menu_family')}, "
            "repeated_menu_family_count="
            f"{recent_progress_summary.get('repeated_menu_family_count')}, "
            "repeated_key_fingerprint="
            f"{recent_progress_summary.get('repeated_key_fingerprint')}, "
            "last_action_family="
            f"{recent_progress_summary.get('last_action_family')}, "
            "escape_recovery_attempted="
            f"{str(recent_progress_summary.get('escape_recovery_attempted')).lower()}, "
            "sticky_blocked_menu_path="
            f"{str(recent_progress_summary.get('sticky_blocked_menu_path')).lower()}, "
            "do_not_repeat_menu_path="
            f"{str(recent_progress_summary.get('do_not_repeat_menu_path')).lower()}"
        )
        if recent_progress_summary.get("do_not_repeat_wait"):
            status_lines.append(
                "Recent progress instruction: do not press STRING_A032 or wait again "
                "until you inspect and fix the visible manager/workshop/order blocker "
                "through real UI evidence."
            )
        if recent_progress_summary.get("do_not_repeat_menu_path"):
            repeated_family = recent_progress_summary.get("repeated_menu_family")
            repeated_keys = recent_progress_summary.get("repeated_key_fingerprint")
            status_lines.append(
                "Recent progress instruction: you are repeating a no-progress "
                f"{repeated_family} path. Do not press the same menu sequence again "
                f"({repeated_keys}). First escape to a verified main-map screen with "
                "LEAVESCREEN, then choose a different route based on visible screen "
                "text. For manager/nobles loops, do not use fixed CURSOR_DOWN counts "
                "unless the Nobles list and target row are visibly confirmed."
            )
            if recent_progress_summary.get("sticky_blocked_menu_path"):
                status_lines.append(
                    "Recent progress instruction: this blocked menu family remains "
                    "forbidden until a later action produces real tile, material, "
                    "job, order, or workshop progress. A no-progress designation, "
                    "cursor move, or screen escape does not make the same blocked "
                    "menu path safe to retry."
                )
            if not recent_progress_summary.get("escape_recovery_attempted"):
                status_lines.append(
                    "Recent progress instruction: your next action must be only "
                    "LEAVESCREEN keys with advance_ticks=0. Do not combine escape "
                    "with D_NOBLES, D_BUILDJOB, D_JOBLIST, cursor movement, or SELECT "
                    "until the next observation confirms the screen."
                )
            else:
                status_lines.append(
                    "Recent progress instruction: a clean LEAVESCREEN recovery has "
                    "already happened, so do not reopen the blocked menu family on "
                    "this turn. For building/workshop loops, do not press D_BUILDING, "
                    "HOTKEY_BUILDING_WORKSHOP, HOTKEY_BUILDING_WORKSHOP_CARPENTER, "
                    "D_BUILDJOB, or BUILDJOB_ADD until a later observation proves a "
                    "new cursor location and a valid visible placement/task screen. "
                    "Choose a different evidence route instead of retrying the same "
                    "workshop/build path."
                )
    if screen_shows_workshop_material_selection:
        status_lines.append(
            "Live UI build feedback: the current visible workshop material "
            "selection screen lists material rows and says Enter: Select; "
            "press SELECT with advance_ticks=0 to choose the highlighted "
            "material instead of exiting, unless the visible screen says Needs "
            "building material."
        )
    elif screen_shows_pending_workshop_construction:
        status_lines.append(
            "Live UI build feedback: the selected Carpenter's Workshop is still "
            "construction-pending. BUILDJOB_ADD is not a valid production action "
            "until the workshop becomes usable; use visible construction evidence "
            "and work metrics to decide whether to wait, inspect jobs, or abandon "
            "this route."
        )
    elif screen_shows_ready_workshop_placement:
        status_lines.append(
            "Live UI build feedback: the current visible workshop placement "
            "screen says Enter: Place and does not show Blocked or Needs "
            "building material; treat older material warnings as stale for "
            "this screen."
        )
    elif ui_build_feedback.get("material_blocked"):
        if ui_build_feedback.get("visible", True):
            status_lines.append(
                "Live UI build feedback: the visible build screen says material is "
                "missing; exit build menus and acquire logs or stone before retrying "
                "workshop placement."
            )
        else:
            status_lines.append(
                "Live UI build feedback: a previous build screen said material was "
                "missing; acquire logs or stone before retrying workshop placement."
            )
    if ui_workshop_feedback.get("placement_blocked"):
        status_lines.append(
            "Live UI workshop feedback: native DF rejected the current carpenter "
            "workshop footprint as blocked; do not retry that exact footprint. "
            "Exit build menus first, then use a fresh workshop target or return "
            "to excavation."
        )
        if ui_workshop_feedback.get("menu_escape_keys"):
            status_lines.append(
                "Live UI workshop feedback: while still in the blocked build menus, "
                "submit only LEAVESCREEN keys with advance_ticks=0."
            )
    if ui_run_progress:
        total_work_delta = int(ui_run_progress.get("total_work_delta") or 0)
        total_excavation_delta = int(ui_run_progress.get("total_excavation_delta") or 0)
        total_material_delta = int(ui_run_progress.get("total_material_delta") or 0)
        successful_targets = int(ui_run_progress.get("successful_targets") or 0)
        status_lines.append(
            "Live UI run progress: "
            f"total_work_delta={total_work_delta}, "
            f"total_excavation_delta={total_excavation_delta}, "
            f"total_material_delta={total_material_delta}, "
            f"successful_targets={successful_targets}"
        )
        if total_excavation_delta >= 10 or successful_targets >= 2:
            available_materials = int(stocks.get("wood") or 0) + int(stocks.get("stone") or 0)
            if available_materials <= 0 or total_material_delta <= 0 or active_material_blocked:
                status_lines.append(
                    "Live UI phase: starter digging exists but building material is "
                    "missing, unusable, or not yet proven by this run. Use material target recommended keys to chop "
                    "a visible tree or mine visible stone/vein wall through the normal "
                    "designation UI before retrying D_BUILDING. D_BUILDING is "
                    "premature on this turn."
                )
            else:
                planned_for_phase = _work_int(
                    work,
                    "carpenter_workshops_planned",
                    default=_work_int(work, "carpenter_workshops"),
                )
                if planned_for_phase > 0 and _proven_carpenter_workshops(work) <= 0:
                    status_lines.append(
                        "Live UI phase: a workshop object is already placed, but "
                        "usable/task proof is still missing. Do not place another "
                        "workshop just to chase score; resolve the existing "
                        "construction or task-menu blocker."
                    )
                else:
                    status_lines.append(
                        "Live UI phase: enough starter digging and building material exist; "
                        "stop using only dig actions and try D_BUILDING for construction."
                    )
    if ui_target_setup.get("ok"):
        status_lines.append(
            "Live UI setup: "
            f"mode={ui_target_setup.get('target_mode', 'starter')}, "
            f"generation={ui_target_setup.get('target_generation', '?')}, "
            f"attempts={ui_target_setup.get('target_attempts', 0)}, "
            f"selection_rect={ui_target_setup.get('selection_rect')}, "
            f"designatable_tiles={ui_target_setup.get('designatable_tiles', 0)}"
        )
        target_z = _int_or_none(ui_work.get("target_z"))
        if target_z is None:
            target_rect = ui_target_setup.get("target_rect") or ui_target_setup.get(
                "selection_rect"
            )
            if isinstance(target_rect, list) and len(target_rect) >= 3:
                target_z = _int_or_none(target_rect[2])
        view_z = _int_or_none(work.get("window_z"))
        if view_z is None:
            view_z = _int_or_none(work.get("cursor_z"))
        if target_z is not None and view_z is not None and target_z != view_z:
            z_key = "CURSOR_UP_Z" if target_z > view_z else "CURSOR_DOWN_Z"
            status_lines.append(
                "Live UI z-level mismatch: "
                f"current view z={view_z}, target z={target_z}. Do not send "
                "target designation or placement keys from this z-level. If "
                "you want to use the shown target, use z-level navigation such "
                f"as {z_key} to return toward it, then wait for the next "
                "observation before acting on target keys. If you are "
                "intentionally exploring this z-level for new rock or "
                "resources, ignore the stale target keys and first verify the "
                "current visible DF cursor/menu with screen_read before "
                "designating."
            )
        status_lines.append(
            "Live UI target note: selection_rect and window are observation "
            "metadata, not a manual cursor route. Use recommended keys when "
            "shown; if they are hidden, do not invent CURSOR offsets from "
            "selection_rect/window unless the screen visibly shows an active "
            "cursor in a cursor-owning DF mode."
        )
        if ui_target_setup.get("target_mode") == "material":
            status_lines.append(
                "Live UI material target: use this shown target to create usable "
                "workshop building material through native designations."
            )
            key_prefix = ui_target_setup.get("recommended_key_prefix")
            if isinstance(key_prefix, list) and key_prefix:
                if ui_target_setup.get("recommended_keys_exit_only"):
                    status_lines.append(
                        "Live UI material recovery: copy only the listed escape "
                        "keys this turn ("
                        + ", ".join(str(key) for key in key_prefix)
                        + "). Do not chain a new designation or build command "
                        "after the escape keys; wait for the next observation "
                        "from the main map before acquiring material."
                    )
                else:
                    status_lines.append(
                        "Live UI material recovery: the recommended sequence first "
                        "exits build menus with "
                        + ", ".join(str(key) for key in key_prefix)
                        + " and then designates the material target."
                    )
        elif ui_target_setup.get("target_mode") == "existing_workshop":
            if _work_int(work, "carpenter_workshop_construction_jobs") > 0:
                status_lines.append(
                    "Live UI existing workshop target: this target points at a "
                    "placed Carpenter's Workshop with a queued construction job. "
                    "If you are in a menu, escape only. If the main map is "
                    "visible, advancing time with empty keys is allowed so the "
                    "construction job can complete. Use D_BUILDJOB only to "
                    "inspect the placed workshop if time advancement fails to "
                    "produce usable workshop proof."
                )
            else:
                status_lines.append(
                    "Live UI existing workshop target: this target points at the "
                    "already placed Carpenter's Workshop. From a verified main-map "
                    "screen, use the recommended D_BUILDJOB key to select that real "
                    "workshop. If wood is available and no carpenter task is "
                    "queued, stay on this workshop route and add/select a visible "
                    "wooden task before returning to starter digging, D_BUILDING, "
                    "D_NOBLES, D_JOBLIST, or manager orders."
                )
        elif ui_target_setup.get("target_mode") == "workshop":
            if screen_shows_blocked_placement:
                status_lines.append(
                    "Live UI workshop target: this is only a candidate 3x3 "
                    "floor target. The visible DF placement screen currently "
                    "says placement is blocked or missing material, so do not "
                    "press SELECT to confirm; trust the visible screen over "
                    "target metadata."
                )
            elif screen_shows_ready_workshop_placement:
                status_lines.append(
                    "Live UI workshop target: current DF screen is a valid "
                    "carpenter workshop placement screen. If your screen_read "
                    "also sees Enter: Place and no Blocked or Needs building "
                    "material warning, press SELECT with advance_ticks=0 to "
                    "move to material selection."
                )
            elif screen_shows_workshop_material_selection:
                status_lines.append(
                    "Live UI workshop target: current DF screen is the "
                    "carpenter workshop material-selection list. If your "
                    "screen_read sees a material row and Enter: Select, press "
                    "SELECT with advance_ticks=0 to choose the highlighted "
                    "material; do not leave the menu just because construction "
                    "has not finished yet."
                )
            else:
                status_lines.append(
                    "Live UI workshop target: this is a candidate 3x3 floor "
                    "target. Use the recommended keys to open native carpenter "
                    "workshop placement, then read the visible placement screen "
                    "before confirming. Only press SELECT if the visible screen "
                    "does not say Blocked or Needs building material."
                )
        recommended_keys = ui_target_setup.get("recommended_keys")
        show_recommended = bool(ui_target_setup.get("show_recommended_keys", True))
        if show_recommended and isinstance(recommended_keys, list) and recommended_keys:
            prefix = (
                "Retry fresh target recommended keys: "
                if ui_target_setup.get("recommended_keys_retry")
                else "Fresh target recommended keys: "
            )
            status_lines.append(prefix + ", ".join(str(key) for key in recommended_keys))
        elif ui_target_setup.get("recommended_keys_suppressed"):
            if ui_target_setup.get("target_progress_seen"):
                reason = "this target already produced real tile progress."
            elif ui_target_setup.get("target_attempts", 0) >= ui_target_setup.get(
                "recommended_key_retry_limit",
                0,
            ):
                reason = "the bounded retry limit was reached."
            else:
                reason = "this target was already attempted."
            status_lines.append("Fresh target recommended keys: hidden because " + reason)
            status_lines.append(
                "Fresh target route: unavailable. Treat the target coordinates "
                "as evidence about the world, not a key sequence; choose a "
                "different productive branch, wait for active work, or first "
                "open and verify a visible DF cursor before manual navigation."
            )

    if risks:
        status_lines.append("Risks: " + ", ".join(risks))

    if reminders:
        status_lines.append("Reminders: " + "; ".join(reminders))

    # If screen text is provided, format for keystroke mode
    if screen_text:
        summary_text = f"""== SCREEN ==
{screen_text}

== STATUS ==
{chr(10).join(status_lines)}"""
        # When the latest result has an explicit matching action identity,
        # render its command above and its result once; history supplies only
        # older outcomes. Validation failures have no matching history step,
        # so they never hide an unrelated executed action.
        last_action_step = (
            last_action_result.get("_action_step")
            if isinstance(last_action_result, dict)
            else None
        )
        latest_history_matches = bool(
            action_history
            and last_action_step is not None
            and action_history[-1].get("step") == last_action_step
        )
        prior_action_history = (
            action_history[:-1] if latest_history_matches else action_history
        )
        if prior_action_history:
            history_lines = []
            for a in prior_action_history:
                history_lines.append(_format_action_history_entry(a))
            summary_text += "\n\n== RECENT ACTION OUTCOMES ==\n" + "\n".join(history_lines)
    else:
        # Original format for toolbox mode
        bullets = [f"- {line}" for line in status_lines]
        if not risks:
            bullets.append("- Risks: none detected")
        if not reminders:
            bullets.append("- Reminders: none")
        summary_text = "\n".join(bullets)

    return summary_text, clean_state

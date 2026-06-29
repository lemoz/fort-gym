"""Observation encoding utilities."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

INVALID_DF_CURSOR = -30000


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


def _format_action_history_entry(action_entry: Dict[str, Any]) -> str:
    step_num = action_entry.get("step", "?")
    intent = action_entry.get("intent", "no intent")
    keys_str = _format_key_preview(action_entry.get("keys", []))
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
        action_entry.get("screen_read")
        if isinstance(action_entry.get("screen_read"), dict)
        else {}
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
            details.append(
                "agent_screen="
                + mode
                + (f"/{confidence}" if confidence else "")
            )
    if last_action_review:
        worked = last_action_review.get("worked")
        if worked is not None:
            details.append(f"agent_prev_worked={worked}")
        if last_action_review.get("should_retry_same_path") is not None:
            details.append(
                "agent_retry_same_path="
                + str(last_action_review.get("should_retry_same_path")).lower()
            )

    return f"  Step {step_num}: {intent} -> [{keys_str}] ({'; '.join(details)})"


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
    for entry in reversed(action_history):
        reasons = entry.get("productive_reasons")
        productive = isinstance(reasons, list) and bool(reasons)
        if productive:
            break
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
    last_entry = action_history[-1]
    last_key_fingerprint = _key_fingerprint(last_entry.get("keys"))
    last_action_family = _action_family(last_entry)
    last_keys = last_entry.get("keys")
    last_was_escape_only = bool(
        isinstance(last_keys, list)
        and last_keys
        and all(str(key) == "LEAVESCREEN" for key in last_keys)
    )

    manager_orders = _to_int(work.get("manager_orders_count"))
    order_qty_left = _to_int(work.get("manager_orders_amount_left"))
    carpenter_workshops = _to_int(work.get("carpenter_workshops"))
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
        "escape_recovery_attempted": last_was_escape_only,
        "agent_marked_bad_menu_path": agent_marked_bad_path,
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
    work = clean_state.get("work") if isinstance(clean_state.get("work"), dict) else {}
    recent_progress_summary = _recent_progress_summary(action_history, work)
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
        screen_shows_ready_workshop_placement
        or screen_shows_workshop_material_selection
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
    active_material_blocked = bool(
        ui_build_feedback.get("material_blocked")
        and not screen_shows_workshop_select_state
    )

    # Build status section
    status_lines = []

    # Game state feedback (critical for agent to know if game is running)
    if pause_state is True:
        status_lines.append("Game Status: PAUSED (press SPACE to unpause)")
    elif pause_state is False:
        status_lines.append("Game Status: RUNNING")

    # Last action result feedback
    if last_action_result is not None:
        accepted = last_action_result.get("accepted", last_action_result.get("ok", True))
        if accepted:
            status_lines.append("Last Action: ACCEPTED")
        else:
            reason = last_action_result.get("reason", last_action_result.get("error", "unknown"))
            status_lines.append(f"Last Action: REJECTED - {reason}")

    # Screen change feedback - critical for agent to know if actions had effect
    if screen_text and previous_screen:
        diff = _compute_screen_diff(previous_screen, screen_text)
        if diff.get("has_prev"):
            if diff.get("screen_identical"):
                status_lines.append("⚠️ WARNING: Screen UNCHANGED - your action may have had NO EFFECT!")
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

    status_lines.extend([
        f"Time: tick {time_tick}",
        f"Population: {population} dwarves",
        (
            f"Food: {stocks.get('food', 0)}, Drink: {stocks.get('drink', 0)}, "
            f"Wood: {stocks.get('wood', 0)}, Stone: {stocks.get('stone', 0)}"
        ),
    ])
    if work:
        status_lines.append(
            "Target room: "
            f"floors={work.get('target_floor_tiles', 0)}/{work.get('target_tiles', 0)}, "
            f"walls={work.get('target_wall_tiles', 0)}, "
            f"designations={work.get('target_dig_designations', 0)}"
        )
        if work.get("cursor_z") is not None or work.get("window_z") is not None:
            cursor_x = work.get("cursor_x")
            cursor_label = (
                "inactive"
                if _is_inactive_df_cursor(cursor_x)
                else "active"
            )
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
        status_lines.append(
            "Utility work: "
            f"manager_orders={work.get('manager_orders_count', 0)}, "
            f"order_qty_left={work.get('manager_orders_amount_left', 0)}, "
            f"carpenter_workshops={work.get('carpenter_workshops', 0)}"
        )
        if (
            int(work.get("manager_orders_count") or 0) > 0
            and int(work.get("manager_orders_amount_left") or 0) > 0
            and int(work.get("carpenter_workshops") or 0) > 0
        ):
            production_note = (
                "Live UI production phase: a real manager order is queued and "
                "a carpenter workshop exists."
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
        if work.get("fortress_plan_name"):
            status_lines.append(
                "Fortress plan: "
                f"connector_floors={work.get('fortress_connector_floor_tiles', 0)}/"
                f"{work.get('fortress_connector_tiles', 0)}, "
                f"workshop_room_floors={work.get('fortress_workshop_room_floor_tiles', 0)}/"
                f"{work.get('fortress_workshop_room_tiles', 0)}, "
                f"completed_spaces={work.get('fortress_complexity_spaces_completed', 0)}/2"
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
            "press SELECT to choose the highlighted material instead of "
            "exiting, unless the visible screen says Needs building material."
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
            if (
                available_materials <= 0
                or total_material_delta <= 0
                or active_material_blocked
            ):
                status_lines.append(
                    "Live UI phase: starter digging exists but building material is "
                    "missing, unusable, or not yet proven by this run. Use material target recommended keys to chop "
                    "a visible tree or mine visible stone/vein wall through the normal "
                    "designation UI before retrying D_BUILDING. D_BUILDING is "
                    "premature on this turn."
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
                    "material warning, press SELECT to place it now."
                )
            elif screen_shows_workshop_material_selection:
                status_lines.append(
                    "Live UI workshop target: current DF screen is the "
                    "carpenter workshop material-selection list. If your "
                    "screen_read sees a material row and Enter: Select, press "
                    "SELECT to choose the highlighted material; do not leave "
                    "the menu just because construction has not finished yet."
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
            status_lines.append(
                prefix + ", ".join(str(key) for key in recommended_keys)
            )
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
            status_lines.append(
                "Fresh target recommended keys: hidden because " + reason
            )
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
        # Add action history if available
        if action_history:
            history_lines = []
            for a in action_history:
                history_lines.append(_format_action_history_entry(a))
            summary_text += f"\n\n== RECENT ACTION OUTCOMES ==\n" + "\n".join(history_lines)
    else:
        # Original format for toolbox mode
        bullets = [f"- {line}" for line in status_lines]
        if not risks:
            bullets.append("- Risks: none detected")
        if not reminders:
            bullets.append("- Reminders: none")
        summary_text = "\n".join(bullets)

    return summary_text, clean_state

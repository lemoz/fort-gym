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
                else:
                    status_lines.append("Live UI feedback: the last action dug real tiles.")
            elif no_progress_streak:
                status_lines.append(
                    "Live UI feedback: the last action changed no tracked tiles; "
                    "do not repeat the same key sequence unless a fresh target is shown."
                )
    if ui_build_feedback.get("material_blocked"):
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
                or ui_build_feedback.get("material_blocked")
            ):
                status_lines.append(
                    "Live UI phase: starter digging exists but building material is "
                    "missing, unusable, or not yet proven by this run. Use material target recommended keys to chop "
                    "a visible tree or mine visible stone/vein wall through the normal "
                    "designation UI before retrying D_BUILDING."
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
        if ui_target_setup.get("target_mode") == "material":
            status_lines.append(
                "Live UI material target: use this shown target to create usable "
                "workshop building material through native designations."
            )
            key_prefix = ui_target_setup.get("recommended_key_prefix")
            if isinstance(key_prefix, list) and key_prefix:
                status_lines.append(
                    "Live UI material recovery: copy the full recommended sequence; "
                    "it first exits build menus with "
                    + ", ".join(str(key) for key in key_prefix)
                    + " and then designates the material target."
                )
        elif ui_target_setup.get("target_mode") == "workshop":
            status_lines.append(
                "Live UI workshop target: the cursor is on a confirmed empty 3x3 "
                "floor footprint. Copy the recommended keys exactly to place a "
                "carpenter workshop there; do not move the placement cursor."
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

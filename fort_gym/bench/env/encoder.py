"""Observation encoding utilities."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def redact_noise(state: Dict[str, Any]) -> Dict[str, Any]:
    """Placeholder hook to strip non-deterministic noise from raw state."""
    return state


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
        f"Food: {stocks.get('food', 0)}, Drink: {stocks.get('drink', 0)}",
    ])

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
                step_num = a.get("step", "?")
                intent = a.get("intent", "no intent")
                keys = a.get("keys", [])
                ticks_advanced = a.get("advance_ticks", 0)
                # Show first few keys to keep it concise
                keys_preview = keys[:5] if len(keys) > 5 else keys
                keys_str = ", ".join(keys_preview)
                if len(keys) > 5:
                    keys_str += f"... (+{len(keys) - 5} more)"
                time_str = f"+{ticks_advanced}t" if ticks_advanced > 0 else "paused"
                history_lines.append(f"  Step {step_num}: {intent} → [{keys_str}] ({time_str})")
            summary_text += f"\n\n== RECENT ACTIONS ==\n" + "\n".join(history_lines)
    else:
        # Original format for toolbox mode
        bullets = [f"- {line}" for line in status_lines]
        if not risks:
            bullets.append("- Risks: none detected")
        if not reminders:
            bullets.append("- Reminders: none")
        summary_text = "\n".join(bullets)

    return summary_text, clean_state

"""Load saved windows in checkpoint-parent order across completion and pauses."""

from pathlib import Path

from .campaign_keyboard_paused import paused_window
from .campaign_keyboard_presave import _read
from .campaign_keyboard_windows import completed_window


def saved_window_sequence(
    root: Path,
    completed: tuple[str, ...],
    paused: tuple[str, ...],
    parents: list[dict],
) -> list[dict]:
    """Validate every record normally once its unique saved parent is available."""
    known = list(parents)
    identities = [row.get("window_id", row.get("saved_segment_id")) for row in known]
    if any(not isinstance(value, str) or not value for value in identities):
        raise ValueError("Saved window sequence requires named saved parents")
    if len(set(identities)) != len(identities):
        raise ValueError("Saved window sequence has duplicate saved parents")
    pending = []
    declared = set(identities)
    for status, filenames in (("completed", completed), ("paused", paused)):
        for filename in filenames:
            identity = filename.removesuffix(".json")
            if identity in declared:
                raise ValueError("Saved window sequence has duplicate record identities")
            declared.add(identity)
            source = _read(root, filename)
            parent = source.get("parent_record")
            if not isinstance(parent, str) or not parent:
                raise ValueError("Saved window sequence requires a declared parent")
            pending.append((status, filename, parent))
    ordered = []
    while pending:
        progressed = False
        for entry in pending[:]:
            status, filename, parent = entry
            if parent not in identities:
                continue
            reader = completed_window if status == "completed" else paused_window
            row = reader(root, filename, known)
            ordered.append(row)
            known.append(row)
            identities.append(row["window_id"])
            pending.remove(entry)
            progressed = True
        if not progressed:
            raise ValueError("Saved window sequence has a missing or cyclic parent")
    return ordered

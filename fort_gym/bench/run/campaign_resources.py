"""Bounded, read-only Linux resource evidence without spawning a subprocess."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import time

PROFILE = "fortgym.native-resource-observations/v1"
_MAX_BYTES = 8192
_MAX_PROCESSES = 4096
_COUNTERS = (
    "pids.current", "pids.max", "pids.peak", "pids.events", "pids.events.local",
    "memory.current", "memory.max", "memory.peak", "memory.events",
)


def _read(path: Path) -> str | None:
    try:
        with path.open("rb") as stream:
            data = stream.read(_MAX_BYTES + 1)
        return data.decode("ascii") if len(data) <= _MAX_BYTES else None
    except (OSError, UnicodeError):
        return None


def capture_resources(
    *, proc: Path = Path("/proc"), cgroup: Path = Path("/sys/fs/cgroup"),
) -> dict:
    """Missing measurements stay unknown; counts cover only visible processes.

    Cgroup PIDs count threads too. Proc counts are lower bounds when a process
    disappears or cannot be inspected, and are not interchangeable with pids.current.
    Never read command lines, environment variables or unrelated filesystem data.
    """
    membership = _read(proc / "self/cgroup")
    # Only the namespaced v2 root is unambiguous without interpreting mountinfo.
    root_bound = membership is not None and "0::/" in membership.splitlines()
    counters = {}
    for name in _COUNTERS:
        raw = _read(cgroup / name) if root_bound else None
        value: object = None
        if raw is not None:
            raw = raw.strip()
            if raw == "max":
                value = "max"
            elif len(raw) <= 20 and raw.isascii() and raw.isdecimal():
                value = int(raw)
            elif name.endswith(("events", "events.local")) and raw:
                parts = [line.split() for line in raw.splitlines()]
                if all(len(row) == 2 and row[0].isidentifier()
                       and len(row[1]) <= 20 and row[1].isascii() and row[1].isdecimal() for row in parts):
                    value = {key: int(count) for key, count in parts}
        counters[name] = value
    states: Counter[str] = Counter()
    inspected = threads = failures = 0
    complete = True
    try:
        for entry in proc.iterdir():
            if not entry.name.isascii() or not entry.name.isdecimal():
                continue
            if inspected + failures >= _MAX_PROCESSES:
                complete = False
                break
            raw = _read(entry / "stat")
            fields = raw.rpartition(") ")[2].split() if raw is not None else []
            if (len(fields) < 18 or len(fields[0]) != 1
                    or fields[0] not in "RSDZTWtXxKWPIN" or len(fields[17]) > 20
                    or not fields[17].isascii() or not fields[17].isdecimal()):
                failures += 1
                complete = False
                continue
            inspected += 1
            states[fields[0]] += 1
            threads += int(fields[17])
    except OSError:
        complete = False
    return {
        "schema_version": PROFILE, "captured_at_unix": time.time(),
        "cgroup_v2_namespace_root_verified": root_bound, "cgroup": counters,
        "visible_processes": inspected if inspected or complete else None,
        "visible_threads": threads if inspected or complete else None,
        "visible_zombies": states["Z"] if inspected or complete else None,
        "process_states": dict(states), "proc_scan_complete": complete,
        "unreadable_processes": failures, "proc_scan_limit": _MAX_PROCESSES,
        "cgroup_pids_include_threads": True,
        "underlying_failure_cause": "not_inferred",
    }

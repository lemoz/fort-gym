"""Post-hoc classification of a disposable copy's two native load-log entries."""

import hashlib
import re

LOG = "events-dfhack.log"
LINE = re.compile(
    rb"\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+0000\] "
    rb"DFHack 0\.47\.05-r8-0-gfed9f763 on Linux; cwd md5: [0-9a-f]{10}; "
    rb"save: campaign-resume; (SC_WORLD_LOADED|SC_MAP_LOADED); game type DWARF_MAIN \(0\)\n"
)


def verify_delta(expected, actual, original_log, copied_log):
    def without_log(rows):
        return [row for row in rows if row["path"] != LOG]

    if without_log(expected) != without_log(actual):
        raise ValueError("Non-log native save files changed")
    for rows, raw in ((expected, original_log), (actual, copied_log)):
        logs = [row for row in rows if row["path"] == LOG]
        if logs != [
            {"path": LOG, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        ]:
            raise ValueError("Load log inventory does not match its bytes")
    if not copied_log.startswith(original_log):
        raise ValueError("Original log prefix changed")
    append = copied_log[len(original_log) :]
    matches = [LINE.fullmatch(line) for line in append.splitlines(keepends=True)]
    if len(matches) != 2 or not all(matches):
        raise ValueError("Expected exactly two DFHack load-event lines")
    if [match.group(1) for match in matches] != [b"SC_WORLD_LOADED", b"SC_MAP_LOADED"]:
        raise ValueError("Unexpected load-event sequence")
    return {
        "path": LOG,
        "source_size_bytes": len(original_log),
        "copied_size_bytes": len(copied_log),
        "appended_bytes": len(append),
        "appended_sha256": hashlib.sha256(append).hexdigest(),
        "source_prefix_unchanged": True,
        "appended_events": ["SC_WORLD_LOADED", "SC_MAP_LOADED"],
        "non_log_files_byte_identical": len(without_log(expected)),
        "whole_copied_save_tree_byte_identical": False,
        "review_scope": "post_hoc_exact_load_log_classification",
    }

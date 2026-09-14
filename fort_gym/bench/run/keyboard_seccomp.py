"""Read an explicitly selected DFHack syscall profile; never disable seccomp."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

PROFILE_LIMIT = 1024 * 1024
PERSONALITY_ARGUMENT = {"index": 0, "value": 262144, "op": "SCMP_CMP_EQ"}


def read_profile(path: str, expected_sha256: str) -> bytes:
    """Verify selected bytes and the narrow launcher allowance, not a policy audit.

    The operator supplies a reviewed, versioned default-deny profile suitable
    for their engine. A digest binds that choice; structural checks cannot prove
    that every other syscall rule matches a particular Docker release.
    """
    source = Path(path)
    if (
        not source.is_absolute()
        or source != source.resolve()
        or any(char in path for char in ("\n", "\r", "\0"))
        or not source.is_file()
        or source.stat().st_size > PROFILE_LIMIT
        or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256)
    ):
        raise ValueError("Seccomp needs one resolved regular profile and exact SHA256")
    with source.open("rb") as stream:
        raw = stream.read(PROFILE_LIMIT + 1)
    if len(raw) > PROFILE_LIMIT or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Seccomp profile bytes differ from the declared SHA256")
    profile = json.loads(raw)
    if (
        not isinstance(profile, dict)
        or profile.get("defaultAction") != "SCMP_ACT_ERRNO"
        or type(profile.get("defaultErrnoRet", 1)) is not int
        or profile.get("defaultErrnoRet", 1) <= 0
        or not isinstance(profile.get("syscalls"), list)
    ):
        raise ValueError("Seccomp profile must retain default-deny behavior")
    launcher_allowed = False
    for rule in profile["syscalls"]:
        if (
            not isinstance(rule, dict)
            or not isinstance(rule.get("names"), list)
            or not rule["names"]
            or any(not isinstance(name, str) or not re.fullmatch(r"[a-z0-9_]+", name)
                   for name in rule["names"])
        ):
            raise ValueError("Seccomp syscall rule is malformed")
        if "personality" not in rule["names"] or rule.get("action") != "SCMP_ACT_ALLOW":
            continue
        arguments = rule.get("args", [])
        if (
            not isinstance(arguments, list)
            or len(arguments) != 1
            or not isinstance(arguments[0], dict)
            or arguments[0].get("index") != 0
            or arguments[0].get("op") != "SCMP_CMP_EQ"
            or type(arguments[0].get("value")) is not int
        ):
            raise ValueError("Seccomp must not allow unconstrained personality calls")
        if (
            rule["names"] == ["personality"]
            and arguments == [PERSONALITY_ARGUMENT]
            and not rule.get("includes")
            and not rule.get("excludes")
        ):
            launcher_allowed = True
    if not launcher_allowed:
        raise ValueError("Seccomp must explicitly allow DFHack personality(262144)")
    return raw

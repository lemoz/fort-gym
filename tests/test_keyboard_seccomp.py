"""Profile parsing is offline; these tests do not establish kernel acceptance."""

import hashlib
import json

import pytest

from fort_gym.bench.run.keyboard_seccomp import PERSONALITY_ARGUMENT, read_profile


def profile():
    return {
        "defaultAction": "SCMP_ACT_ERRNO",
        "defaultErrnoRet": 1,
        "syscalls": [
            {"names": ["read", "write"], "action": "SCMP_ACT_ALLOW"},
            {"names": ["personality"], "action": "SCMP_ACT_ALLOW",
             "args": [dict(PERSONALITY_ARGUMENT)]},
        ],
    }


def retained(tmp_path, value):
    path = tmp_path / "policy.json"
    raw = json.dumps(value, indent=3).encode() + b"\n"
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest(), raw


def test_selected_profile_bytes_are_not_reserialized_or_widened(tmp_path):
    path, sha, raw = retained(tmp_path, profile())
    assert read_profile(str(path), sha) == raw
    assert path.read_bytes() == raw


@pytest.mark.parametrize("field,value", [
    ("defaultAction", "SCMP_ACT_ALLOW"),
    ("defaultErrnoRet", 0),
    ("defaultErrnoRet", True),
    ("syscalls", []),
    ("syscalls", "unconfined"),
])
def test_default_deny_and_explicit_launcher_allowance_are_required(tmp_path, field, value):
    path, sha, _ = retained(tmp_path, {**profile(), field: value})
    with pytest.raises(ValueError):
        read_profile(str(path), sha)


@pytest.mark.parametrize("change", [
    {"args": []},
    {"args": [{"index": 0, "value": 262144, "op": "SCMP_CMP_MASKED_EQ"}]},
    {"args": [{"index": 1, "value": 262144, "op": "SCMP_CMP_EQ"}]},
    {"args": [{"index": 0, "value": True, "op": "SCMP_CMP_EQ"}]},
    {"args": [None]},
    {"names": ["*"]},
    {"names": [True]},
    {"names": ["personality", "mount"]},
    {"includes": {"caps": ["CAP_SYS_ADMIN"]}},
    {"excludes": {"arches": ["amd64"]}},
])
def test_broad_conditional_or_malformed_personality_allowances_are_rejected(tmp_path, change):
    value = profile()
    value["syscalls"][-1].update(change)
    path, sha, _ = retained(tmp_path, value)
    with pytest.raises(ValueError):
        read_profile(str(path), sha)


def test_an_extra_unconstrained_rule_cannot_hide_behind_the_narrow_rule(tmp_path):
    value = profile()
    value["syscalls"].append({"names": ["personality"], "action": "SCMP_ACT_ALLOW"})
    path, sha, _ = retained(tmp_path, value)
    with pytest.raises(ValueError, match="unconstrained"):
        read_profile(str(path), sha)


def test_regular_file_and_exact_original_digest_are_required(tmp_path):
    path, sha, _ = retained(tmp_path, profile())
    with pytest.raises(ValueError, match="SHA256"):
        read_profile(str(path), "0" * 64)
    link = tmp_path / "linked.json"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="resolved"):
        read_profile(str(link), sha)
    with pytest.raises(ValueError):
        read_profile("unconfined", sha)
    path.write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(ValueError):
        read_profile(str(path), sha)

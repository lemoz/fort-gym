import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from fort_gym.bench.agent import codex_allowance as module


def account():
    return {"account": {"type": "chatgpt", "email": "private@example.test"}}


def limits():
    return {
        "rateLimitsByLimitId": {
            "codex": {
                "primary": {"usedPercent": 42, "windowDurationMins": 300, "resetsAt": 2000},
                "secondary": None,
            }
        }
    }


def test_current_quota_is_not_an_atomic_reservation_or_reported_charge():
    result = module.evaluate_allowance(account(), limits(), now=1000)
    assert result["allowed"] is True
    assert result["atomic_account_reservation"] is False
    assert result["reported_charge_usd"] is None
    assert "private@" not in json.dumps(result)


@pytest.mark.parametrize(
    "change",
    [
        {"usedPercent": True},
        {"usedPercent": float("nan")},
        {"usedPercent": 90},
        {"usedPercent": 100},
        {"usedPercent": -1},
        {"resetsAt": 1000},
        {"resetsAt": None},
        {"windowDurationMins": None},
    ],
)
def test_invalid_stale_or_consumed_windows_are_not_admitted(change):
    value = limits()
    value["rateLimitsByLimitId"]["codex"]["primary"].update(change)
    assert not module.evaluate_allowance(account(), value, now=1000)["allowed"]


def test_multi_bucket_missing_codex_does_not_fall_back_to_legacy():
    value = limits()
    value["rateLimits"] = deepcopy(value["rateLimitsByLimitId"]["codex"])
    value["rateLimitsByLimitId"] = {}
    assert not module.evaluate_allowance(account(), value, now=1000)["allowed"]


def test_any_known_window_blocks_and_no_window_is_unknown():
    value = limits()
    bucket = value["rateLimitsByLimitId"]["codex"]
    bucket["secondary"] = {**bucket["primary"], "usedPercent": 95}
    assert not module.evaluate_allowance(account(), value, now=1000)["allowed"]
    bucket.update(primary=None, secondary=None)
    assert not module.evaluate_allowance(account(), value, now=1000)["allowed"]


@pytest.mark.parametrize("kind", ["apiKey", None, "amazonBedrock"])
def test_no_account_or_different_auth_is_not_subscription(kind):
    assert not module.evaluate_allowance({"account": {"type": kind}}, limits(), now=1000)["allowed"]


def test_rpc_uses_only_initialization_and_read_methods(monkeypatch):
    code = """
import json,sys
expected=['initialize','initialized','account/read','account/rateLimits/read']
for method in expected:
    message=json.loads(sys.stdin.readline())
    assert message['method']==method
    if method=='initialized': continue
    result = {'account': {'type':'chatgpt'}} if method=='account/read' else {}
    if method=='account/rateLimits/read': result={'rateLimits': {'primary': None}}
    print(json.dumps({'id':message['id'],'result':result}), flush=True)
"""
    monkeypatch.setattr(
        module, "account_command", lambda executable: [sys.executable, "-u", "-c", code]
    )
    identity, quota = module._account_read(Path(sys.executable), 3)
    assert identity == {"account": {"type": "chatgpt"}}
    assert quota == {"rateLimits": {"primary": None}}


@pytest.mark.parametrize("reply", ["{}", "[]", '{"id":0,"error":{"message":"failure"}}'])
def test_rpc_failure_never_starts_a_turn(monkeypatch, reply):
    code = "import sys;sys.stdin.readline();print(" + repr(reply) + ",flush=True)"
    monkeypatch.setattr(
        module, "account_command", lambda executable: [sys.executable, "-u", "-c", code]
    )
    with pytest.raises(ValueError):
        module._account_read(Path(sys.executable), 2)

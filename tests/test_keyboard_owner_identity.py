"""An inspection failure must not turn a live observer into a stopped feed."""

from types import SimpleNamespace

import pytest

from scripts import campaign_keyboard_observe as observer


@pytest.mark.parametrize(
    "returncode,stdout,stderr",
    [(1, "", "ps: operation not permitted"), (0, "", ""), (2, "", "inspection failed")],
)
def test_inspection_failure_is_not_owner_death(monkeypatch, returncode, stdout, stderr):
    monkeypatch.setattr(
        observer.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=returncode, stdout=stdout, stderr=stderr
        ),
    )
    with pytest.raises(RuntimeError, match="inspect"):
        observer.owner_identity(4321)


@pytest.mark.parametrize(
    "returncode,stdout,expected",
    [
        (1, "", None),
        (
            0,
            "Sat Sep 12 00:00:00 2026 python -u owner.py\n",
            "Sat Sep 12 00:00:00 2026 python -u owner.py",
        ),
    ],
)
def test_only_verified_missing_or_present_owner_is_returned(
    monkeypatch, returncode, stdout, expected
):
    calls = []

    def inspect(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(observer.subprocess, "run", inspect)
    assert observer.owner_identity(4321) == expected
    assert calls == [
        (
            ["ps", "-p", "4321", "-o", "lstart=,command="],
            {"capture_output": True, "text": True, "timeout": 5},
        )
    ]

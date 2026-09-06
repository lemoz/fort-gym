from __future__ import annotations

import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import campaign_process


def test_sigterm_unwinds_finally_and_restores_the_original_handler():
    before = signal.getsignal(signal.SIGTERM)
    events = []
    with pytest.raises(KeyboardInterrupt, match="termination requested"):
        with campaign_process.termination_as_interrupt():
            try:
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            finally:
                events.append("native teardown can execute")
    assert events and signal.getsignal(signal.SIGTERM) is before


@pytest.mark.parametrize("failure", [KeyboardInterrupt(), subprocess.TimeoutExpired("test", 1)])
def test_worker_is_reaped_before_propagating_controller_interruption(monkeypatch, failure):
    waits, signals = [], []

    def wait(*, timeout):
        waits.append(timeout)
        if len(waits) == 1:
            raise failure
        return 0

    def spawn(command, **kwargs):
        assert command == ["synthetic-worker"]
        assert kwargs["start_new_session"] is True
        return SimpleNamespace(pid=123456, wait=wait)

    monkeypatch.setattr(campaign_process.subprocess, "Popen", spawn)
    monkeypatch.setattr(campaign_process.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(type(failure)):
        campaign_process.run_worker(["synthetic-worker"], env={}, stdout=None, timeout=900)
    assert waits == [900, 5]
    assert signals == [(123456, signal.SIGTERM), (123456, signal.SIGKILL)]


def test_worker_resisting_termination_is_killed_and_reaped(monkeypatch):
    waits, signals = [], []

    def wait(*, timeout):
        waits.append(timeout)
        if len(waits) <= 2:
            raise subprocess.TimeoutExpired("synthetic-worker", timeout)
        return -9

    monkeypatch.setattr(
        campaign_process.subprocess, "Popen", lambda *a, **k: SimpleNamespace(pid=123456, wait=wait)
    )
    monkeypatch.setattr(campaign_process.os, "killpg", lambda pid, sig: signals.append(sig))
    with pytest.raises(subprocess.TimeoutExpired):
        campaign_process.run_worker(["synthetic-worker"], env={}, stdout=None, timeout=900)
    assert waits == [900, 5, 5]
    assert signals == [signal.SIGTERM, signal.SIGKILL, signal.SIGKILL]


def test_successful_worker_does_not_send_a_signal(monkeypatch):
    monkeypatch.setattr(
        campaign_process.subprocess,
        "Popen",
        lambda *a, **k: SimpleNamespace(pid=123456, wait=lambda **kw: 0),
    )
    signals = []
    monkeypatch.setattr(campaign_process.os, "killpg", lambda *args: signals.append(args))
    campaign_process.run_worker(["synthetic-worker"], env={}, stdout=None, timeout=900)
    assert not signals


def test_real_provider_free_child_is_reaped_after_timeout(monkeypatch):
    original = subprocess.Popen
    children = []

    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(campaign_process.subprocess, "Popen", spawn)
    with pytest.raises(subprocess.TimeoutExpired):
        campaign_process.run_worker(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            env={},
            stdout=subprocess.DEVNULL,
            timeout=0.1,
        )
    assert len(children) == 1 and children[0].returncode is not None

"""Bound the model worker lifetime so controller termination reaches teardown."""

from __future__ import annotations

import os
import signal
import subprocess
from contextlib import contextmanager


@contextmanager
def termination_as_interrupt():
    """SIGTERM unwinds Python finally blocks, including owned native-game cleanup."""
    previous = signal.getsignal(signal.SIGTERM)

    def terminate(signum, frame):
        raise KeyboardInterrupt("Campaign termination requested")

    signal.signal(signal.SIGTERM, terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def run_worker(command: list[str], *, env: dict, stdout, timeout: float) -> None:
    """Reap the exact owned worker session before the game launcher tears down.

    subprocess.run's KeyboardInterrupt path can leave the child running. This worker
    has its own session, distinct from the isolated native game's owned session."""
    process = subprocess.Popen(
        command, env=env, stdout=stdout, stderr=subprocess.STDOUT, start_new_session=True
    )

    def stop(requested_signal):
        try:
            os.killpg(process.pid, requested_signal)
        except ProcessLookupError:
            pass

    try:
        code = process.wait(timeout=timeout)
        if code:
            raise subprocess.CalledProcessError(code, command)
    except BaseException:
        stop(signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            stop(signal.SIGKILL)
            process.wait(timeout=5)
        finally:
            # Also remove a child RPC process surviving the worker's own exit.
            stop(signal.SIGKILL)
        raise

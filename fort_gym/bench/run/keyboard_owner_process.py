"""Read one process identity without starting or controlling it."""
import subprocess
import os


def process_identity(pid: int) -> str | None:
    if type(pid) is not int or pid <= 1:
        raise ValueError("A specific owner PID is required")
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart=,command="],
        capture_output=True, text=True, timeout=5,
    )
    if result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip():
        return None
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("Owner process identity is unavailable")
    return result.stdout.strip()


def capture_owner_process() -> dict:
    """Optional spectator metadata must not prevent an otherwise valid run."""
    pid = os.getpid()
    value: dict = {"pid": pid, "identity": None}
    try:
        value["identity"] = process_identity(pid)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        value["observation_error"] = type(error).__name__
    return value

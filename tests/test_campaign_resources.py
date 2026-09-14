"""Resource evidence is available without fork, with explicit unknowns."""

from pathlib import Path
import subprocess

import pytest

from fort_gym.bench.run import campaign_resources as resources


def fixture_proc(tmp_path):
    proc, cgroup = tmp_path / "proc", tmp_path / "cgroup"
    (proc / "self").mkdir(parents=True)
    cgroup.mkdir()
    (proc / "self/cgroup").write_text("0::/\n")
    return proc, cgroup


def process(proc, pid, state, threads):
    directory = proc / str(pid)
    directory.mkdir()
    fields = [state, *["0"] * 16, str(threads), "0", "12345"]
    (directory / "stat").write_text(f"{pid} (comm with ) parens) " + " ".join(fields))


def test_v2_counts_include_threads_and_zombies_without_subprocess(tmp_path, monkeypatch):
    proc, cgroup = fixture_proc(tmp_path)
    process(proc, 100, "S", 3)
    process(proc, 101, "Z", 1)
    for name, value in {
        "pids.current": "256\n", "pids.max": "256\n", "pids.events": "max 3\n",
        "memory.current": "1000000\n", "memory.max": "max\n",
        "memory.events": "low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n",
    }.items():
        (cgroup / name).write_text(value)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("no subprocess"))
    result = resources.capture_resources(proc=proc, cgroup=cgroup)
    assert result["cgroup"]["pids.current"] == 256
    assert result["cgroup"]["pids.events"] == {"max": 3}
    assert result["cgroup"]["memory.max"] == "max"
    assert result["visible_processes"] == 2 and result["visible_threads"] == 4
    assert result["visible_zombies"] == 1 and result["proc_scan_complete"]
    assert result["underlying_failure_cause"] == "not_inferred"


def test_missing_linux_surfaces_are_unknown_not_zero(tmp_path):
    result = resources.capture_resources(proc=tmp_path / "absent", cgroup=tmp_path)
    assert result["visible_processes"] is None
    assert result["visible_threads"] is None and result["visible_zombies"] is None
    assert not result["proc_scan_complete"]
    assert all(value is None for value in result["cgroup"].values())


@pytest.mark.parametrize("membership", ["0::/different\n", "2:pids:/\n", ""])
def test_does_not_misattribute_mount_root_counters(tmp_path, membership):
    proc, cgroup = fixture_proc(tmp_path)
    (proc / "self/cgroup").write_text(membership)
    (cgroup / "pids.current").write_text("9999")
    assert resources.capture_resources(proc=proc, cgroup=cgroup)["cgroup"]["pids.current"] is None


@pytest.mark.parametrize("counter", ["-1", "1.0", "bad", "9" * 8193, "9" * 8000, "\N{ARABIC-INDIC DIGIT ONE}"])
def test_unreadable_or_invalid_counter_is_unknown(tmp_path, counter):
    proc, cgroup = fixture_proc(tmp_path)
    (cgroup / "pids.current").write_text(counter)
    assert resources.capture_resources(proc=proc, cgroup=cgroup)["cgroup"]["pids.current"] is None


def test_partial_proc_scan_is_explicit_lower_bound(tmp_path, monkeypatch):
    proc, cgroup = fixture_proc(tmp_path)
    process(proc, 100, "S", 2)
    (proc / "101").mkdir()  # A disappeared/unreadable process.
    result = resources.capture_resources(proc=proc, cgroup=cgroup)
    assert result["visible_processes"] == 1 and result["visible_threads"] == 2
    assert result["unreadable_processes"] == 1 and not result["proc_scan_complete"]
    monkeypatch.setattr(resources, "_MAX_PROCESSES", 1)
    assert not resources.capture_resources(proc=proc, cgroup=cgroup)["proc_scan_complete"]


def test_private_command_and_environment_files_are_never_read(tmp_path, monkeypatch):
    proc, cgroup = fixture_proc(tmp_path)
    process(proc, 100, "S", 1)
    original = Path.open

    def checked(path, *args, **kwargs):
        assert path.name not in ("cmdline", "environ")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", checked)
    resources.capture_resources(proc=proc, cgroup=cgroup)

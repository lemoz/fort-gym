from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from fort_gym.bench.run.residue_audit import (
    BatchResidueAuditor,
    ResidueExpectation,
)


class FakeCommands:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.container_residue: dict[str, str] = {}
        self.listener_residue: dict[int, str] = {}
        self.foreign_containers: set[str] = set()
        self.fail_program: str | None = None

    def __call__(self, argv: Sequence[str]) -> tuple[int, str, str]:
        command = tuple(argv)
        self.calls.append(command)
        if self.fail_program == command[0]:
            return 1, "", "synthetic probe failure"
        if command[:3] == ("docker", "ps", "--all"):
            run_filter = command[-1]
            run_id = run_filter.rsplit("=", 1)[-1]
            return 0, self.container_residue.get(run_id, ""), ""
        if command[:2] == ("ss", "-Hlnpt"):
            port = int(command[-1].rsplit(":", 1)[-1])
            return 0, self.listener_residue.get(port, ""), ""
        if command[:4] == ("docker", "inspect", "--type", "container"):
            return (
                (0, "[]", "")
                if command[-1] in self.foreign_containers
                else (1, "", "missing")
            )
        raise AssertionError(f"unexpected command: {command}")


def _expectation(tmp_path: Path) -> ResidueExpectation:
    evidence = tmp_path / "evidence" / "terminal.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("{}\n", encoding="utf-8")
    return ResidueExpectation(
        run_ids=("run-a", "run-b"),
        ports=(58_000, 58_001),
        process_group_ids=(20_001, 20_002),
        mount_paths=(tmp_path / "mount-a", tmp_path / "mount-b"),
        temporary_paths=(tmp_path / "tmp-a", tmp_path / "tmp-b"),
        retained_evidence_paths=(evidence,),
        foreign_process_ids=(30_001,),
        foreign_container_ids=("foreign-canary",),
        port_lock_dir=tmp_path / "leases",
    )


def test_clean_batch_is_audited_twice_and_retains_only_evidence(tmp_path: Path) -> None:
    commands = FakeCommands()
    commands.foreign_containers.add("foreign-canary")
    expected = _expectation(tmp_path)
    evidence_path = expected.retained_evidence_paths[0]
    journal = (tmp_path / "audit" / "cleanup-audit.jsonl").resolve()
    auditor = BatchResidueAuditor(
        command_probe=commands,
        process_group_exists=lambda _pgid: False,
        process_exists=lambda pid: pid == 30_001,
        mount_exists=lambda _path: False,
        path_exists=lambda path: path == evidence_path,
        lease_available=lambda _port, _lock_dir: True,
    )

    first, second = auditor.audit_twice(expected, journal_path=journal)

    assert first.ok is True
    assert second.ok is True
    assert first.residues == {
        "containers": {},
        "process_groups": [],
        "listeners": {},
        "leases": [],
        "mounts": [],
        "temporary_paths": [],
        "probe_errors": [],
    }
    assert first.foreign_canaries["all_untouched"] is True
    assert first.retained_evidence == [str(evidence_path)]
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    assert [row["pass_index"] for row in rows] == [1, 2]
    assert [row["ok"] for row in rows] == [True, True]


def test_every_residue_class_or_lost_canary_fails_closed(tmp_path: Path) -> None:
    commands = FakeCommands()
    commands.container_residue["run-a"] = "a" * 64
    commands.listener_residue[58_000] = "LISTEN 0 128 127.0.0.1:58000"
    expected = _expectation(tmp_path)
    auditor = BatchResidueAuditor(
        command_probe=commands,
        process_group_exists=lambda pgid: pgid == 20_001,
        process_exists=lambda _pid: False,
        mount_exists=lambda path: path.name == "mount-a",
        path_exists=lambda path: path.name in {"tmp-a", "terminal.json"},
        lease_available=lambda port, _lock_dir: port != 58_001,
    )

    report = auditor.audit(expected)

    assert report.ok is False
    assert report.residues["containers"] == {"run-a": ["a" * 64]}
    assert report.residues["process_groups"] == [20_001]
    assert report.residues["listeners"] == {"58000": ["LISTEN 0 128 127.0.0.1:58000"]}
    assert report.residues["leases"] == [58_001]
    assert report.residues["mounts"] == [str(tmp_path / "mount-a")]
    assert report.residues["temporary_paths"] == [str(tmp_path / "tmp-a")]
    assert report.foreign_canaries["all_untouched"] is False


def test_probe_error_is_evidence_not_an_empty_inventory(tmp_path: Path) -> None:
    commands = FakeCommands()
    commands.fail_program = "docker"
    expected = ResidueExpectation(
        run_ids=("run-a",),
        ports=(58_000,),
        port_lock_dir=tmp_path.resolve(),
    )
    auditor = BatchResidueAuditor(
        command_probe=commands,
        process_group_exists=lambda _pgid: False,
        process_exists=lambda _pid: True,
        lease_available=lambda _port, _lock_dir: True,
    )

    report = auditor.audit(expected)

    assert report.ok is False
    assert report.residues["probe_errors"] == [
        {
            "probe": "containers",
            "run_id": "run-a",
            "error": "synthetic probe failure",
        }
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"run_ids": (), "ports": ()},
        {"run_ids": ("unsafe/run",), "ports": (58_000,)},
        {"run_ids": ("run-a", "run-b"), "ports": (58_000, 58_000)},
        {"run_ids": ("run-a",), "ports": (0,)},
        {
            "run_ids": ("run-a",),
            "ports": (58_000,),
            "temporary_paths": (Path("relative"),),
        },
    ],
)
def test_expectation_rejects_ambiguous_or_unsafe_scope(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        ResidueExpectation(**kwargs)

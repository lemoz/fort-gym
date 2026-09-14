"""Versioned read-only evidence bindings, independent of any VM topology."""

from pathlib import Path, PurePosixPath
import hashlib
import re

SCHEMA = "fortgym.portable-owner-continuity-audit/v2"


def artifact_hashes(attempt: Path, paths: list[Path]) -> dict[str, str]:
    """Bind regular metadata files without publishing their private contents."""
    result = {}
    for path in sorted(set(paths)):
        relative = path.relative_to(attempt).as_posix()
        if path.resolve() != path or not path.is_file():
            raise ValueError("Audit input is not a resolved regular file")
        with path.open("rb") as stream:
            result[relative] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


def verify_artifact_hashes(attempt: Path, expected: dict) -> None:
    if not isinstance(expected, dict) or not expected:
        raise ValueError("Run audit must bind its retained evidence files")
    paths = []
    for relative, value in expected.items():
        if (
            not isinstance(relative, str)
            or not relative
            or PurePosixPath(relative).is_absolute()
            or ".." in PurePosixPath(relative).parts
            or "\\" in relative
            or not isinstance(value, str)
            or not re.fullmatch(r"[a-f0-9]{64}", value)
        ):
            raise ValueError("Invalid run-audit evidence path or digest")
        paths.append(attempt / relative)
    if artifact_hashes(attempt, paths) != expected:
        raise ValueError("Run evidence changed after its audit")

"""Prepare/check a standalone image context, without an engine or game launch.

This is source packaging, not a base-image installer or native acceptance.
The base's game, Python, libraries and bindings must be obtained independently.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fort_gym.bench.run.keyboard_image_context import (
    check_context,
    prepare_context,
    sha256,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Copy committed source and declared bindings")
    prepare.add_argument("--source", type=Path, required=True)
    prepare.add_argument("--inputs", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    check = commands.add_parser(
        "check", help="Verify an existing context without its original source"
    )
    check.add_argument("--output", type=Path, required=True)
    check.add_argument("--receipt-sha256", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_context(args.source, json.loads(args.inputs.read_text()), args.output)
    else:
        result = check_context(args.output, expected_sha256=args.receipt_sha256)
    print(
        json.dumps(
            {
                "schema_version": result["schema_version"],
                "source_revision": result["inputs"]["source_revision"],
                "source_tree": result["source_tree"],
                "context_receipt_sha256": sha256(args.output / "context.json"),
                "context_files": len(result["files"]),
                "context_bytes": sum(row["bytes"] for row in result["files"].values()),
                "context_verified": True,
                "docker_contacted": False,
                "image_built": False,
                "native_game_verified": False,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()

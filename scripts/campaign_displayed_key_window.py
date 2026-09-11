"""Prepare a frozen matched 64-to-128 own-save configuration, without launching."""

import argparse
import json
from pathlib import Path

from fort_gym.bench.run.displayed_key_window import prepare_window


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--index", default="experiments/evidence/keyboard_binding_comparison_20260911_index.json"
    )
    parser.add_argument("--campaign-id", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            prepare_window(args.root, args.index, args.campaign_id), indent=2, allow_nan=False
        )
    )


if __name__ == "__main__":
    main()

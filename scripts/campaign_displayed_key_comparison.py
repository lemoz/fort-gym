"""Print a source-pinned displayed-key comparison; no game, model or publishing calls."""

import argparse
import json
from pathlib import Path

from fort_gym.bench.eval.displayed_key_comparison import read_comparison


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--index", required=True, help="Project-relative public result index")
    parser.add_argument("--boundary", type=int, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            read_comparison(args.project_root, args.index, boundary=args.boundary),
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()

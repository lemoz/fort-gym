"""Export selected audited portable-owner windows; never start a game or model."""
import argparse
import json
from pathlib import Path

from fort_gym.bench.run.keyboard_docker_recording import export, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=Path, action="append", required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--audit-sha256", required=True)
    parser.add_argument("--id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = export(args.attempt, args.audit, args.audit_sha256, identity=args.id, title=args.title)
    with args.output.open("x") as stream:
        json.dump(value, stream, separators=(",", ":"), allow_nan=False)
        stream.write("\n")
    print(json.dumps({"frames": len(value["frames"]), "sha256": sha(args.output),
                      "model_calls": 0, "gameplay_inputs": 0, "website_published": False}))


if __name__ == "__main__":
    main()

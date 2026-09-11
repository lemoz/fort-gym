"""Connect the frozen bounded courier to the matched own-save reload gate.

The separate owner is responsible for an already-started, bound container and
all teardown. This adapter never starts, stops or repairs a game or model run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from continuation_state import require, verify_loaded_state

PREFIX_DIGEST_SCRIPT = (
    "import hashlib,json,pathlib; "
    "p=pathlib.Path('/evidence/astra/segment-0/loop'); "
    "print(json.dumps({n:hashlib.sha256((p/n).read_bytes()).hexdigest() "
    "for n in ('trace.jsonl','usage.jsonl')}))"
)


def collect_loaded(native: Any, name: str) -> dict[str, Any]:
    """Read only the native process's initial snapshots and immutable prefixes."""
    owner = native.owner
    command = owner.DOCKER + ["exec", name]
    files = {
        "agent": "agent-before.json",
        "history": "history-before.json",
        "before": "native-before.json",
    }
    result = {
        key: json.loads(owner.output(command + ["/bin/cat", "/evidence/astra/segment-0/" + file]))
        for key, file in files.items()
    }
    result["prefix_sha256"] = json.loads(
        owner.output(command + ["/opt/python/bin/python3.11", "-c", PREFIX_DIGEST_SCRIPT])
    )
    return result


def gated_answer(native: Any, origin: dict, name: str, out: Path) -> Any:
    """Check the first native request before allowing the existing model transport."""
    checked = False

    def answer(request: dict, **kwargs: Any) -> Any:
        nonlocal checked
        if not checked:
            require(
                native.verify_checkpoint(origin["checkpoint"]) == origin["manifest"],
                "Parent changed before the first model call",
            )
            receipt = verify_loaded_state(
                origin, request=request, metrics=native.metrics, **collect_loaded(native, name)
            )
            native.owner.publish(out / "native-load-gate.json", receipt)
            checked = True
        return native.owner.answer_request(request, **kwargs)

    return answer


def serve(native: Any, origin: dict, *, name: str, out: Path, decisions: list[dict]) -> None:
    """Preserve the frozen courier's full memory chain, response cap and admission."""
    from fort_gym.bench.run.keyboard_window_courier import DockerExchange, serve_window

    owner = native.owner
    exchange = DockerExchange(
        name=name,
        out=out,
        docker=owner.DOCKER,
        environment=owner.transport.VM_ENV,
        output=owner.output,
        run=owner.run,
    )
    serve_window(
        exchange,
        origin["condition"],
        origin["window"],
        initial_memory=origin["agent"]["memory"],
        executable=Path("/opt/homebrew/bin/codex"),
        decisions=decisions,
        answer=gated_answer(native, origin, name, out),
        emit=lambda value: print(json.dumps(value), flush=True),
    )

"""Reconcile a whole window's private model receipts across saved segments.

The supplied reviewers must validate actual provider events and admission pauses.
This read-only composition checks ordering, transport copies, memory and totals;
it does not replace native checkpoint verification or VM teardown checks.
"""

from collections.abc import Callable
from pathlib import Path

from ..agent.keyboard_exchange import read
from .keyboard_segment_audit import _require


def verify_window_receipts(
    native: Path,
    out: Path,
    *,
    condition: dict,
    control: dict,
    initial_memory: str,
    responses: int,
    status: str,
    review_response: Callable[[Path, dict], dict],
    review_pause: Callable[[Path], dict],
) -> dict:
    """Return private reconciled receipts and final memory, without model calls."""
    _require(
        type(responses) is int
        and responses >= 0
        and status in {"completed", "paused"}
        and isinstance(initial_memory, str),
        "Invalid settled window receipt boundary",
    )
    model = out / "model"
    folders = sorted(
        (path.parent for path in model.glob("*/summary.json")),
        key=lambda path: read(path / "summary.json")["decision_index"],
    )
    _require(
        all(not path.is_symlink() and path.parent == model for path in folders),
        "Receipt directory is not owned by this window",
    )
    names = {path.name for path in folders}
    for root, filenames in (
        (model, ("claim.json", "request.json", "response.json")),
        (native / "exchange", ("request.json", "response.json")),
    ):
        for filename in filenames:
            _require(
                names == {path.parent.name for path in root.glob("*/" + filename)},
                "Unsettled or missing model request, claim or response",
            )
    _require(
        control["model_decisions"] == [read(path / "summary.json") for path in folders],
        "Controller summary differs from saved model receipts",
    )
    reviews, pauses, actions = [], [], []
    memory = initial_memory
    for index, folder in enumerate(folders):
        request, summary = read(folder / "request.json"), read(folder / "summary.json")
        decision = read(folder / "response.json")["result"]
        _require(
            type(summary["decision_index"]) is int
            and summary["decision_index"] == index
            and request["memory"] == memory
            and [request["screen"]["width"], request["screen"]["height"]]
            == condition["screen_size"],
            "Model request reset memory, skipped a response or changed the screen",
        )
        for name in ("request.json", "response.json"):
            _require(
                read(folder / name) == read(native / "exchange" / folder.name / name),
                "Host and native model exchange copies differ",
            )
        _require(type(summary["model_dispatched"]) is bool, "Unsettled dispatch status")
        if summary["model_dispatched"]:
            receipt = review_response(folder.resolve(), condition)
            _require(
                type(receipt["total_tokens"]) is int and receipt["total_tokens"] >= 0,
                "Invalid provider token total",
            )
            reviews.append(receipt)
            actions.append(decision["action"])
            _require(
                type(decision["action_grammar_valid"]) is bool, "Unknown action grammar"
            )
            if decision["action_grammar_valid"]:
                memory = decision["action"]["memory_update"]
                _require(isinstance(memory, str), "Invalid model memory update")
        else:
            _require(
                index == len(folders) - 1 and status == "paused",
                "A pre-dispatch pause must end the window",
            )
            pauses.append(review_pause(folder.resolve()))
    _require(
        responses == len(reviews)
        and all(
            type(control[key]) is int and control[key] == responses
            for key in ("provider_calls", "confirmed_model_calls")
        ),
        "Saved actions and actual provider receipts do not reconcile",
    )
    return {
        "receipt_reviews": reviews,
        "admission_pauses": pauses,
        "actions": actions,
        "final_memory": memory,
        "new_tokens": sum(receipt["total_tokens"] for receipt in reviews),
        "new_responses": responses,
    }

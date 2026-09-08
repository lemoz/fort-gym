import threading
import time

import pytest

from fort_gym.bench.agent import keyboard_exchange as module


@pytest.mark.parametrize("selection", [
    {}, {"model": "gpt-6-astra", "reasoning_effort": "medium"},
    {"model": "gpt-5.6-sol", "reasoning_effort": "high"},
    {"model": "gpt-5.6-terra", "reasoning_effort": "low"},
])
def test_exchange_binds_response_to_exact_screen_memory_and_request(tmp_path, selection):
    values = []
    thread = threading.Thread(
        target=lambda: values.append(
            module.exchange_decision(
                tmp_path,
                {"width": 1, "height": 1, "tiles": [[65, 7, 0]]},
                "remember",
                None,
                timeout_seconds=2,
                **selection,
            )
        )
    )
    thread.start()
    try:
        deadline = time.monotonic() + 1
        requests = []
        while not requests and time.monotonic() < deadline:
            requests = list(tmp_path.glob("*/request.json"))
            time.sleep(0.01)
        assert len(requests) == 1
        request = module.read(requests[0])
        module.validate_request(request)
        assert request["memory"] == "remember"
        if selection:
            assert request["schema_version"] == "fortgym.keyboard-exchange-request/v2"
            assert module.request_selection(request) == (
                selection["model"], selection["reasoning_effort"],
            )
            for field in selection:
                assert module.digest(request) != module.digest({**request, field: "changed"})
        else:
            assert request["schema_version"] == "fortgym.keyboard-exchange-request/v1"
            assert "model" not in request and "reasoning_effort" not in request
        module.publish(
            requests[0].parent / "response.json",
            {"request_sha256": module.digest(request), "result": {"test": "receipt"}},
        )
        thread.join(timeout=2)
        assert values == [{"test": "receipt"}]
    finally:
        thread.join(timeout=3)


def test_published_files_are_complete_and_cannot_be_overwritten(tmp_path):
    path = tmp_path / "response.json"
    module.publish(path, {"first": True})
    with pytest.raises(FileExistsError):
        module.publish(path, {"second": True})
    assert module.read(path) == {"first": True}
    assert list(tmp_path.iterdir()) == [path]


def test_request_hash_changes_if_screen_memory_or_id_changes():
    original = {"screen": "A", "memory": "plan", "request_id": "one"}
    for key in original:
        assert module.digest(original) != module.digest({**original, key: "different"})


def test_symlink_and_oversized_exchange_are_rejected(tmp_path):
    path = tmp_path / "original.json"
    module.publish(path, {"test": True})
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        module.read(link)
    with pytest.raises(ValueError):
        module.publish(tmp_path / "large.json", {"text": "x" * module.MAX_BYTES})
    assert not (tmp_path / "large.json").exists()

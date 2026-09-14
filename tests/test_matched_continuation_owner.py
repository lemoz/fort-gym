"""Exercise the real owner lifecycle with fake transport, never a VM or model."""

from copy import deepcopy
import importlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "experiments/keyboard_binding_comparison_continuations_20260911"


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(BASE))
    return importlib.import_module("local_owner"), importlib.import_module("local_lifecycle")


@pytest.mark.parametrize("name", ["sol", "terra", "astra"])
def test_all_models_use_own_save_launcher_and_literal_readonly_package(modules, name, tmp_path):
    owner, _ = modules
    condition = ROOT / "experiments/keyboard_binding_comparison_20260911" / f"{name}-condition.json"
    window = tmp_path / "window.json"
    window.write_text('{"synthetic":true}')
    command = owner.native_arguments(condition.name)
    assert command[:3] == ["-m", "scripts.campaign_keyboard_native", "run"]
    assert command[command.index("--condition") + 1] == "/launch/" + condition.name
    assert command[command.index("--checkpoint") + 1] == "/seed-evidence/astra/segment-0/checkpoint"
    assert "--snapshot" not in command and "--restart-source" not in command
    with tarfile.open(fileobj=io.BytesIO(owner.launch_archive(condition, window))) as archive:
        assert archive.getnames() == ["launch", "launch/" + condition.name, "launch/window.json"]
        assert archive.getmember("launch/window.json").mode == 0o444
        assert archive.extractfile("launch/" + condition.name).read() == condition.read_bytes()
        assert archive.extractfile("launch/window.json").read() == window.read_bytes()


@pytest.fixture
def runtime(modules, tmp_path, monkeypatch):
    _, lifecycle = modules
    events = []
    faults = {"tag": None, "admitted": True}
    config_file = tmp_path / "vm.yaml"
    config_file.write_text("unchanged VM")
    spec = {
        "name": "owned-window",
        "volume": "new-evidence",
        "source_volume": "own-prior-save",
        "image": "sha256:" + "a" * 64,
        "session": tmp_path / "new-window",
        "config": config_file,
        "seccomp": tmp_path / "seccomp.json",
        "arguments": ["native-window"],
        "archive": b"fake archive",
        "binding": {},
        "origin": {
            "window": {"expected_campaign_id": "synthetic-sol-r1"},
            "condition": {"model": "gpt-5.6-sol"},
            "checkpoint": tmp_path / "checkpoint",
            "manifest": {"sha256": "saved"},
        },
    }
    config = {
        "Image": spec["image"],
        "Config": {"User": "dfh", "Labels": {"fortgym.owner": spec["name"]}},
        "HostConfig": {
            "Init": True,
            "PidsLimit": 256,
            "NetworkMode": "none",
            "PortBindings": {},
            "Memory": 1610612736,
            "MemorySwap": 1610612736,
            "NanoCpus": 2000000000,
        },
        "Mounts": [
            {"Destination": "/seed-evidence", "Name": spec["source_volume"], "RW": False},
            {"Destination": "/evidence", "Name": spec["volume"], "RW": True},
        ],
    }

    def publish(path, value):
        with path.open("x") as stream:
            json.dump(value, stream)

    def run(command, tag, *args, **kwargs):
        events.append(tag)
        if faults["tag"] == tag:
            raise RuntimeError("synthetic " + tag)
        if tag == "evidence-copy":
            destination = spec["session"] / "attempt/evidence/astra"
            destination.mkdir(parents=True)
            publish(destination / "result.json", {"status": "synthetic, not native proof"})
        return 0

    def output(command):
        if command[0] == "colima":
            return "Filesystem blocks used available percent path\n/dev/mock 4000000 1000000 3000000 25% /var/lib/docker"
        if command[1] == "ps":
            return ""
        if command[1] == "volume":
            return spec["source_volume"]
        if command[1] == "image":
            return json.dumps(
                [{"Id": spec["image"], "Architecture": "amd64", "Config": {"User": "dfh"}}]
            )
        if command[1] == "inspect":
            if "--format" not in command:
                return json.dumps([config])
            if "Labels" in command[-1]:
                return spec["name"]
            return '{"Running":false,"ExitCode":0}'
        raise AssertionError(command)

    transport = SimpleNamespace(VM_ENV={}, interrupted=lambda *_: None)
    owner = SimpleNamespace(
        DOCKER=["docker"],
        COLIMA=["colima"],
        transport=transport,
        output=output,
        run=run,
        publish=publish,
        stopped=lambda: True,
        REVISION="native",
        CONFIG_SHA=lifecycle.sha(config_file),
        read_allowance=lambda *args, **kwargs: {"allowed": faults["admitted"]},
    )
    native = SimpleNamespace(owner=owner, verify_checkpoint=lambda _: spec["origin"]["manifest"])

    def courier(native, origin, *, name, out, decisions):
        events.append("courier")
        if faults["tag"] == "courier":
            raise RuntimeError("synthetic courier")
        folder = out / "model/00000000000000000000000000000001"
        folder.mkdir(parents=True)
        publish(folder / "claim.json", {})
        decisions.append({"model_dispatched": True})

    monkeypatch.setattr(
        lifecycle.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0)
    )
    return lifecycle, native, spec, courier, events, faults, config


def test_bounded_owner_retains_evidence_and_tears_down_without_claiming_acceptance(runtime):
    lifecycle, native, spec, courier, events, _, _ = runtime
    before = Path.cwd()
    result = lifecycle.execute(native, spec, courier)
    assert Path.cwd() == before
    assert result["status"] == "terminal_pending_audit"
    assert result["native_result_audited"] is False and result["provider_calls"] == 1
    assert result["vm_observed_stopped"] is True
    assert result["original_checkpoint_verified_unchanged"] is True
    assert events == [
        "vm-start",
        "container-create",
        "native-start",
        "courier",
        "container-stop",
        "container-log",
        "container-final-state",
        "evidence-copy",
        "guest-poweroff",
        "vm-stop",
    ]
    assert (spec["session"] / "attempt/result.json").is_file()


@pytest.mark.parametrize("fault", ["vm-start", "container-create", "native-start", "courier"])
def test_primary_failure_still_stops_vm_and_writes_original_failure(runtime, fault):
    lifecycle, native, spec, courier, events, faults, _ = runtime
    faults["tag"] = fault
    with pytest.raises(RuntimeError, match=fault):
        lifecycle.execute(native, spec, courier)
    result = json.loads((spec["session"] / "attempt/result.json").read_text())
    assert result["status"] == "failed" and result["error_type"] == "RuntimeError"
    assert events[-2:] == ["guest-poweroff", "vm-stop"]
    assert result["vm_observed_stopped"] is True


@pytest.mark.parametrize("fault", ["container-stop", "evidence-copy", "guest-poweroff", "vm-stop"])
def test_cleanup_failure_is_retained_without_skipping_later_cleanup(runtime, fault):
    lifecycle, native, spec, courier, events, faults, _ = runtime
    faults["tag"] = fault
    result = lifecycle.execute(native, spec, courier)
    assert result["status"] == "failed"
    assert any(key.endswith("error_type") for key in result)
    assert events[-1] == "vm-stop"


def test_admission_pause_creates_no_vm_or_model_call(runtime):
    lifecycle, native, spec, courier, events, faults, _ = runtime
    faults["admitted"] = False
    result = lifecycle.execute(native, spec, courier)
    assert events == []
    assert result["status"] == "budget_limited_pause" and result["provider_calls"] == 0
    assert result["vm_started"] is False


def test_an_existing_window_cannot_be_relaunched(runtime):
    lifecycle, native, spec, courier, events, _, _ = runtime
    spec["session"].mkdir()
    with pytest.raises(ValueError, match="unused"):
        lifecycle.execute(native, spec, courier)
    assert events == []


def test_container_cannot_mount_a_peer_save_or_make_source_writable(runtime):
    lifecycle, _, spec, _, _, _, config = runtime
    for value in ("peer-save", True):
        changed = deepcopy(config)
        changed["Mounts"][0]["Name" if isinstance(value, str) else "RW"] = value
        with pytest.raises(ValueError, match="mount"):
            lifecycle.verify_container(changed, spec)

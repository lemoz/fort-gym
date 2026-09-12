"""Offline storage-amendment contracts. These tests never start a VM or model."""

from copy import deepcopy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "experiments/keyboard_binding_comparison_continuations_20260911"


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(BASE))
    return (
        importlib.import_module("storage_amendment"),
        importlib.import_module("local_owner"),
        importlib.import_module("local_lifecycle"),
    )


def test_versioned_declaration_matches_the_exact_public_binding(modules):
    amendment, _, lifecycle = modules
    value = json.loads(amendment.DECLARATION.read_text())
    assert value["status"] == "executed_verified"
    assert amendment.sha(amendment.DECLARATION) == amendment.EXPECTED_BINDING["declaration_sha256"]
    binding = dict(value["storage_binding"])
    binding["declaration_sha256"] = amendment.sha(amendment.DECLARATION)
    assert amendment.verify_binding(binding, binding["campaign_id"]) == binding
    assert binding["minimum_guest_free_kib"] == lifecycle.MINIMUM_FREE_KIB == 1572864
    assert value["verification"]["model_calls"] == value["verification"]["gameplay_inputs"] == 0
    assert value["verification"]["container_volume_image_inventory_unchanged"] is True


@pytest.mark.parametrize(
    "key,value",
    [
        ("campaign_id", "bindings-comparison-20260911-sol-r2"),
        ("first_step", 0),
        ("target_next_step", 256),
        ("disk_gib_after", 48),
        ("disk_gib_before", 40),
        ("cpu", 4),
        ("memory_gib", 4),
        ("root_disk_gib", 16),
        ("minimum_guest_free_kib", 1000),
        ("mandatory_teardown", 1),
        ("model_or_prompt_changes", 0),
        ("native_source_or_image_changes", True),
        ("other_configuration_changes", True),
        ("original_config_sha256", "a" * 64),
        ("vm_config_sha256", "a" * 64),
        ("operation_receipt_sha256", "a" * 64),
        ("declaration_sha256", "a" * 64),
        ("private_path", "/private/do-not-export"),
    ],
)
def test_changed_conditions_types_or_private_extras_are_rejected(modules, key, value):
    amendment, _, _ = modules
    binding = dict(amendment.EXPECTED_BINDING)
    binding[key] = value
    with pytest.raises(ValueError, match="Storage amendment"):
        amendment.verify_binding(binding, amendment.EXPECTED_BINDING["campaign_id"])


def test_amendment_cannot_be_applied_to_an_earlier_attempt(modules):
    amendment, _, _ = modules
    with pytest.raises(ValueError, match="campaign"):
        amendment.verify_binding(amendment.EXPECTED_BINDING, "bindings-comparison-20260911-sol-r2")


@pytest.fixture
def proof(modules, monkeypatch):
    amendment, _, _ = modules
    real_sha = amendment.sha
    monkeypatch.setattr(
        amendment,
        "sha",
        lambda path: (
            amendment.EXPECTED_BINDING["operation_receipt_sha256"]
            if path == amendment.OPERATION
            else real_sha(path)
        ),
    )
    return amendment


def test_explicit_canonical_amendment_requires_both_retained_digests(proof, monkeypatch):
    binding = proof.load_binding(proof.DECLARATION, proof.EXPECTED_BINDING["campaign_id"])
    assert binding == proof.EXPECTED_BINDING
    real_sha = proof.sha
    monkeypatch.setattr(
        proof, "sha", lambda path: "0" * 64 if path == proof.OPERATION else real_sha(path)
    )
    with pytest.raises(ValueError, match="receipt changed"):
        proof.load_binding(proof.DECLARATION, proof.EXPECTED_BINDING["campaign_id"])


def test_copy_or_modified_declaration_cannot_be_selected(proof, tmp_path, monkeypatch):
    copied = tmp_path / "copy.json"
    copied.write_bytes(proof.DECLARATION.read_bytes())
    with pytest.raises(ValueError, match="canonical"):
        proof.load_binding(copied, proof.EXPECTED_BINDING["campaign_id"])
    monkeypatch.setattr(proof, "DECLARATION", copied)
    copied.write_text("{}")
    with pytest.raises(ValueError, match="declaration"):
        proof.load_binding(copied, proof.EXPECTED_BINDING["campaign_id"])


@pytest.fixture
def specification(modules, proof, tmp_path, monkeypatch):
    _, owner, _ = modules
    window_path = BASE / "astra-r2-window-64-128.json"
    window = json.loads(window_path.read_text())
    campaign = window["expected_campaign_id"]
    checkpoint = tmp_path / "parent/evidence/astra/segment-0/checkpoint"
    checkpoint.mkdir(parents=True)
    image = "sha256:" + "a" * 64
    (checkpoint.parents[3] / "container-config.json").write_text(
        json.dumps(
            {
                "Image": image,
                "Mounts": [
                    {
                        "Destination": "/evidence",
                        "Name": "fort-gym-" + campaign + "-evidence",
                    }
                ],
            }
        )
    )
    runtime = SimpleNamespace(
        BASE=tmp_path / "runs",
        transport=SimpleNamespace(APP=tmp_path / "vm"),
        RUNTIME=tmp_path / "runtime",
        CONFIG_SHA=proof.EXPECTED_BINDING["original_config_sha256"],
        SECCOMP_SHA="b" * 64,
        IMAGE=image,
    )
    config_sha = {"value": proof.EXPECTED_BINDING["vm_config_sha256"]}
    real_sha = owner.sha
    monkeypatch.setattr(
        owner,
        "sha",
        lambda path: (
            config_sha["value"]
            if path.name == "colima.yaml"
            else runtime.SECCOMP_SHA
            if path.name == "seccomp-moby27-dfhack.json"
            else real_sha(path)
        ),
    )
    origin = {"window": window, "checkpoint": checkpoint, "manifest": {"sha256": "c" * 64}}
    return owner, SimpleNamespace(owner=runtime), origin, window_path, config_sha


def test_new_storage_is_not_accepted_implicitly_and_never_changes_game_arguments(
    specification, proof
):
    owner, native, origin, window, config_sha = specification
    with pytest.raises(ValueError, match="configuration"):
        owner.specification(native, origin, window, "d" * 40)
    amended = owner.specification(native, origin, window, "d" * 40, proof.DECLARATION)
    assert amended["binding"]["storage_amendment"] == proof.EXPECTED_BINDING
    assert amended["binding"]["vm_config_sha256"] == proof.EXPECTED_BINDING["vm_config_sha256"]
    config_sha["value"] = native.owner.CONFIG_SHA
    legacy = owner.specification(native, origin, window, "d" * 40)
    assert "storage_amendment" not in legacy["binding"]
    assert legacy["binding"]["vm_config_sha256"] == native.owner.CONFIG_SHA
    for key in ("arguments", "archive", "name", "volume", "source_volume", "session", "image"):
        assert amended[key] == legacy[key]


def test_launch_arguments_only_change_explicit_disk_capacity_and_preserve_config(modules):
    amendment, _, lifecycle = modules
    assert lifecycle.start_arguments({"binding": {}}) == lifecycle.START_ARGS
    spec = {
        "binding": {
            "storage_amendment": dict(amendment.EXPECTED_BINDING),
            "vm_config_sha256": amendment.EXPECTED_BINDING["vm_config_sha256"],
            "minimum_guest_free_kib": lifecycle.MINIMUM_FREE_KIB,
        },
        "origin": {"window": {"expected_campaign_id": amendment.EXPECTED_BINDING["campaign_id"]}},
    }
    args = lifecycle.start_arguments(spec)
    assert args == ["--disk=40" if arg == "--disk=32" else arg for arg in lifecycle.START_ARGS] + [
        "--save-config=false"
    ]
    changed = deepcopy(spec)
    changed["binding"]["minimum_guest_free_kib"] = 1
    with pytest.raises(ValueError, match="execution binding"):
        lifecycle.start_arguments(changed)
    changed = deepcopy(spec)
    changed["binding"]["vm_config_sha256"] = amendment.EXPECTED_BINDING["original_config_sha256"]
    with pytest.raises(ValueError, match="execution binding"):
        lifecycle.start_arguments(changed)


def test_release_verifies_amendment_bytes_in_the_exact_source_commit(
    modules, proof, monkeypatch
):
    _, owner, _ = modules
    inspected = []

    def committed(command, **kwargs):
        assert command[:2] == ["git", "show"]
        relative = command[2].split(":", 1)[1]
        path = ROOT / relative
        inspected.append(path)
        return b"uncommitted amendment" if path == proof.DECLARATION else path.read_bytes()

    monkeypatch.setattr(owner.subprocess, "check_output", committed)
    with pytest.raises(ValueError, match="declaration source changed"):
        owner.verify_release(None, "d" * 40, "123", proof.DECLARATION)
    assert proof.DECLARATION in inspected

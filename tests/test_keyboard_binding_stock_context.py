"""Recorded inventory scope, with synthetic trader fixtures kept out of results."""

import copy
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from fort_gym.bench.api import keyboard_binding_campaign as campaign
from fort_gym.bench.api.keyboard_binding_stock_context import stock_context


def recorded():
    return campaign.read_result(campaign.LATEST_RESULT_PATH, campaign.LATEST_RESULT_SHA256)


def trader_fixture():
    result = recorded()
    result["saved_metrics"]["food_stock"] = 438
    inventory = result["food_measurement"]["final_inventory"]
    inventory.update(units=438, scanned_units=438, trader_units=395)
    return result


def test_existing_registered_food_count_is_preserved_with_exact_endpoint_context():
    original = recorded()
    before = copy.deepcopy(original)
    context = stock_context(original)
    assert context["scope"] == "final_checkpoint_only"
    assert context["responses"] == 96
    assert context["checkpoint_sha256"] == original["checkpoint_sha256"]
    assert context["food"] == {
        "measurement_status": "complete",
        "raw_units": 58,
        "trader_flagged_units": 0,
        "units_without_trader_flag": 58,
    }
    assert context["drink"] == {"raw_units": 121, "trader_flagged_units": None}
    assert context["ownership_and_accessibility_verified"] is False
    assert context["production_or_sustainability_verified"] is False
    data = campaign.keyboard_binding_campaign()
    assert data["stock_context"] == context
    assert data["responses"] == 96
    assert data["saved_metrics"] == original["saved_metrics"]
    assert data["timeline"][-32:] == original["timeline"]
    assert original == before


def test_trader_goods_are_visible_without_redefining_raw_stock_or_claiming_ownership():
    result = trader_fixture()
    before = copy.deepcopy(result)
    context = stock_context(result)
    assert context["food"]["raw_units"] == 438
    assert context["food"]["trader_flagged_units"] == 395
    assert context["food"]["units_without_trader_flag"] == 43
    assert context["ownership_and_accessibility_verified"] is False
    assert result == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("trader_units", 439),
        ("trader_units", -1),
        ("trader_units", True),
        ("trader_units", 1.5),
        ("units", 437),
        ("scanned_units", 437),
        ("complete", False),
        ("source", "unverified"),
        ("scope", "fortress-owned food"),
    ],
)
def test_invalid_or_mislabelled_inventory_is_rejected(field, value):
    result = trader_fixture()
    result["food_measurement"]["final_inventory"][field] = value
    with pytest.raises(ValueError):
        stock_context(result)


@pytest.mark.parametrize(
    "field,value", [("food_stock", True), ("food_stock", -1), ("drink_stock", 1.5)]
)
def test_invalid_raw_stock_is_not_treated_as_an_unknown_or_integer(field, value):
    result = recorded()
    result["saved_metrics"][field] = value
    with pytest.raises(ValueError):
        stock_context(result)


@pytest.mark.parametrize("mode", ["missing", "null", "no_inventory"])
def test_missing_inventory_keeps_trader_share_unknown_not_zero(mode):
    result = recorded()
    if mode == "missing":
        result.pop("food_measurement")
    else:
        result["food_measurement"] = None if mode == "null" else {}
    food = stock_context(result)["food"]
    assert food == {
        "measurement_status": "unavailable",
        "raw_units": 58,
        "trader_flagged_units": None,
        "units_without_trader_flag": None,
    }


def test_partial_food_scan_does_not_publish_partial_counts_as_complete_inventory():
    result = recorded()
    result["saved_metrics"]["food_stock"] = None
    result["food_measurement"]["final_inventory"].update(
        complete=False,
        units=None,
        list_read_failures=1,
    )
    food = stock_context(result)["food"]
    assert food == {
        "measurement_status": "incomplete",
        "raw_units": None,
        "trader_flagged_units": None,
        "units_without_trader_flag": None,
    }


def test_extra_inventory_fields_cannot_expose_private_data():
    result = recorded()
    result["food_measurement"]["private_path"] = "/Users/private/source"
    result["food_measurement"]["final_inventory"]["model_memory"] = "private memory"
    public = json.dumps(stock_context(result))
    assert (
        "/Users/" not in public and "model_memory" not in public and "private memory" not in public
    )


def test_bad_inventory_makes_campaign_unavailable_without_affecting_historical_endpoint(
    monkeypatch,
):
    from fort_gym.bench.api import server

    client = TestClient(server.app)
    historical = client.get("/public/keyboard-binding-results").content
    read = campaign.read_result

    def corrupted(path, digest):
        result = read(path, digest)
        if path == campaign.LATEST_RESULT_PATH:
            result["food_measurement"]["final_inventory"]["trader_units"] = 999
        return result

    monkeypatch.setattr(campaign, "read_result", corrupted)
    assert client.get("/public/keyboard-binding-campaign").status_code == 503
    assert client.get("/public/keyboard-binding-results").content == historical


@pytest.mark.parametrize("mode", ["recorded", "trader", "unavailable", "incomplete", "legacy"])
def test_inventory_text_scope_unknowns_and_stale_response_checks(mode):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node unavailable")
    result = trader_fixture() if mode == "trader" else recorded()
    if mode == "unavailable":
        result.pop("food_measurement")
    if mode == "incomplete":
        result["saved_metrics"]["food_stock"] = None
        result["food_measurement"]["final_inventory"].update(
            complete=False,
            units=None,
            list_read_failures=1,
        )
    data = campaign.keyboard_binding_campaign()
    data.update(saved_metrics=result["saved_metrics"], stock_context=stock_context(result))
    if mode == "legacy":
        data.pop("stock_context")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            node,
            str(root / "tests/keyboard_binding_stock_context_dom.cjs"),
            str(root / "web/static/campaign-binding-campaign.js"),
        ],
        input=json.dumps({"data": data, "mode": mode}),
        text=True,
        capture_output=True,
        check=True,
    )

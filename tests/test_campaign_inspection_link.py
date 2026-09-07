"""Authored condition identity only; no captured native state or model result."""

from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def test_tracker_serves_the_updated_script_without_adding_a_result_row():
    from fort_gym.bench.api import server

    with TestClient(server.app) as client:
        page = client.get("/campaigns")
        assert page.status_code == 200 and "campaign-feed.js?v=12" in page.text
        script = client.get("/static/campaign-feed.js")
        assert script.status_code == 200
        assert "local-native-qwen35-year-two-inspection-v1" in script.text
        rows = client.get("/public/campaign-feed").json()["campaigns"]
        assert not any(
            row["condition_id"] == "local-native-qwen35-year-two-inspection-v1" for row in rows
        )


def test_inspection_condition_link_requires_the_published_exact_digest():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")
    subprocess.run(
        [
            node,
            "-e",
            """
const assert = require('node:assert/strict');
const helpers = require(process.argv[1]);
const row = {
 condition_id: 'local-native-qwen35-year-two-inspection-v1',
 configuration_sha256: 'ec7c987aef51ce61970ba6c52ea1efd03e887e2ae7c6af87297e9dcef00a1093',
 code_revision: '48d9ed6d94a598b44c4cfbe10a0df4badcb189ad'
};
assert.equal(helpers.configurationUrl(row),
 'https://github.com/lemoz/fort-gym/blob/48d9ed6d94a598b44c4cfbe10a0df4badcb189ad/experiments/campaigns/local_native_qwen35_year_two_inspection_v1.json');
for (const configuration_sha256 of [undefined, null, '', 'a'.repeat(64),
 '1001cbc943c2c5747158946cc024a35919c6483ad11e516884af7b6a4b29c90c']) {
 assert.equal(helpers.configurationUrl({...row, configuration_sha256}), null);
}
assert.equal(helpers.configurationUrl({...row, code_revision: '../main'}), null);
assert.equal(helpers.configurationUrl({...row, condition_id: 'unknown-condition'}), null);
""",
            str(ROOT / "web/static/campaign-feed.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

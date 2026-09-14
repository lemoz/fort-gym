import json
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def test_website_sections_share_current_recordings_and_label_history():
    from fort_gym.bench.api.server import app

    client = TestClient(app)
    for route in ["/", "/worlds", "/results", "/protocols", "/findings", "/live"]:
        response = client.get(route)
        assert response.status_code == 200
        assert 'href="/#watch-root"' in response.text
        assert "publication-note" in response.text or route in ("/", "/worlds", "/results")
    for route in ["/", "/results"]:
        html = client.get(route).text
        assert "data-published-recordings" in html
        assert "/static/published-recordings.mjs" in html
    home = client.get("/").text
    assert "/public/worlds" not in home
    assert 'id="latest-model">Loading' not in home
    findings = client.get("/findings").text
    assert "Historical research · July 11, 2026" in findings
    assert "not the current campaign state" in findings
    assert "Historical replay unavailable" in findings
    assert client.get("/static/published-recordings.mjs").status_code == 200
    assert "Current exploratory recordings" in client.get("/results").text
    assert "fort-eval-easy-p1-g7-v3" in client.get("/results").text


def test_catalog_metadata_is_derived_and_original_findings_are_preserved():
    directory = ROOT / "web/static/recordings"
    for row in json.loads((directory / "catalog.json").read_text())["recordings"]:
        recording = json.loads((directory / (row["id"] + ".json")).read_text())
        for key in [
            "model", "control_profile", "first_decision", "last_decision",
            "saved_through_decision", "recording_status",
        ]:
            assert row[key] == recording[key]
        assert row["frame_count"] == len(recording["frames"])
    manifest = json.loads((ROOT / "web/static/findings-v1.json").read_text())
    assert manifest["as_of"] == "2026-07-11"
    assert len(manifest["findings"]) == 7


def test_site_publication_client_regressions():
    subprocess.run(
        ["node", "--test", str(ROOT / "tests/site_publication_client.mjs")],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )

"""The earlier keyboard outcome stays immutable and separate from corrected v2."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "web/static/recordings"


def test_v1_keyboard_replay_is_complete_and_audit_bound():
    raw = (RECORDINGS / "controls-p1-keyboard-1-128.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "db74af4eb5a3c13297c363aecb9cfc0dad028f708edfdb9db9d7cd353a81e6b8"
    )
    data = json.loads(raw)
    assert data["source_revision"] == "422c915d23bf828371be481d3079a23bbb3e9e94"
    assert data["audit_sha256"] == (
        "9202a9fd406b8d5835fd59a0757478a73ab73faf4e0323b7c3c9885314e009cc"
    )
    assert [frame["decision"] for frame in data["frames"]] == list(range(1, 129))
    assert data["saved_through_decision"] == 128
    assert sum(frame["after"]["ticks_advanced"] for frame in data["frames"]) == 83800
    assert data["frames"][-1]["after"]["population"] == 7
    assert data["frames"][63]["after"]["tick"] == data["frames"][64]["before"]["tick"]
    assert all(frame["accepted"] for frame in data["frames"])
    forbidden = {"memory", "memory_update", "reasoning", "analysis", "request",
                 "response", "provider_events", "account", "access_token", "api_key", "prompt"}

    def check(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for item in value.values():
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    check(data)


def test_v1_publication_labels_do_not_claim_a_corrected_comparison():
    catalog = json.loads((RECORDINGS / "catalog.json").read_text())["recordings"]
    assert catalog[0]["id"] == "controls-p1-keyboard-1-128"
    assert catalog[0]["title"].endswith("(v1)")
    assert "campaign" not in catalog[0]
    page = (ROOT / "web/worlds.html").read_text()
    assert "separate from the corrected v2 controls study" in page
    assert "final save has not had a separate fresh-reload check" in page


def test_each_gallery_preview_has_the_status_target_used_by_the_client():
    class Gallery(HTMLParser):
        def __init__(self):
            super().__init__()
            self.current = None
            self.statuses = {}

        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == "article" and "data-recording-preview" in values:
                self.current = values["data-recording-preview"]
                self.statuses[self.current] = 0
            if self.current and "data-preview-status" in values:
                self.statuses[self.current] += 1

        def handle_endtag(self, tag):
            if tag == "article":
                self.current = None

    gallery = Gallery()
    gallery.feed((ROOT / "web/worlds.html").read_text())
    assert len(gallery.statuses) == 17
    assert set(gallery.statuses.values()) == {1}

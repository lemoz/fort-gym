"""Synthetic publication checks, not new gameplay or deployment evidence."""

import hashlib
import json

import pytest

from fort_gym.bench.api import campaign_records as records
from fort_gym.bench.run.campaign_feed import CampaignFeed, initialize_feed

CONFIG = {"condition_id": "test-condition", "models": ["test-model"]}


@pytest.fixture
def published(tmp_path, monkeypatch):
    monkeypatch.setattr(records, "PUBLISHED_BUNDLES", ("test-bundle.json",))
    bundle = {
        "schema_version": "fortgym.published-campaign-bundle/v1",
        "configuration": CONFIG,
        "source_snapshot_receipt_sha256": "f" * 64,
        "campaigns": [
            {
                "schema_version": "fortgym.public-campaign-state/v1",
                "campaign_id": "test-campaign",
                "segment_id": "segment-000001",
                "model": "test-model",
                "condition_id": "test-condition",
                "code_revision": "a" * 40,
                "configuration_sha256": hashlib.sha256(
                    json.dumps(CONFIG, sort_keys=True).encode()
                ).hexdigest(),
                "updated_at": "2020-01-01T00:00:00+00:00",
                "lifecycle": "finished",
                "segment_status": "bounded_segment_complete",
                "cleanup_verified": True,
                "checkpoint_verified": True,
                "committed_steps": 2,
                "elapsed_ticks": 123,
            }
        ],
    }
    path = tmp_path / "experiments/evidence/test-bundle.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(bundle))
    return tmp_path, path, bundle


def test_recorded_results_do_not_claim_live_configuration(published):
    root, _, _ = published
    feed = records.campaign_feed(None, project_root=root)
    assert feed["configured"] is False and feed["published_snapshots"] == 1
    assert feed["campaigns"][0]["publication"] == "versioned_snapshot"
    assert feed["campaigns"][0]["freshness"] == "recorded"
    assert feed["campaigns"][0]["elapsed_ticks"] == 123
    assert feed["campaigns"][0]["declared_starting_snapshot_receipt_sha256"] == "f" * 64
    assert feed["comparison_rankings_available"] is False


def test_published_data_is_reprojected_and_unlisted_files_ignored(published):
    root, path, bundle = published
    bundle["private_path"] = "/private/secret"
    bundle["campaigns"][0].update(
        agent_memory="secret-prompt", current_metrics={"raw": "secret-world"}
    )
    path.write_text(json.dumps(bundle))
    (path.parent / "unlisted.json").write_text('{"private":"unlisted-secret"}')
    output = json.dumps(records.campaign_feed(None, project_root=root))
    assert "secret" not in output and "private_path" not in output and "agent_memory" not in output


@pytest.mark.parametrize(
    "change",
    [
        {"lifecycle": "running"},
        {"cleanup_verified": False},
        {"model": "other-model"},
        {"condition_id": "other-condition"},
        {"configuration_sha256": "b" * 64},
    ],
)
def test_unverified_or_mismatched_snapshot_is_not_published(published, change):
    root, path, bundle = published
    bundle["campaigns"][0].update(change)
    path.write_text(json.dumps(bundle))
    with pytest.raises(ValueError):
        records.campaign_feed(None, project_root=root)


def test_missing_duplicate_and_oversized_publication_fail(published):
    root, path, bundle = published
    bundle["campaigns"] *= 2
    path.write_text(json.dumps(bundle))
    with pytest.raises(ValueError, match="identity"):
        records.published_records(root)
    path.write_text(" " * (records.MAX_BYTES + 1))
    with pytest.raises(ValueError, match="bounded"):
        records.published_records(root)
    path.unlink()
    with pytest.raises(ValueError, match="regular"):
        records.published_records(root)


def test_published_data_does_not_mask_broken_live_source(published):
    root, _, _ = published
    with pytest.raises(ValueError):
        records.campaign_feed(root / "missing-live", project_root=root)


def test_matching_live_identity_updates_without_duplicate_or_rollback(published):
    root, path, bundle = published
    live = root / "live"
    initialize_feed(live)
    publisher = CampaignFeed(
        live,
        campaign_id="test-campaign",
        segment_id="segment-000002",
        model="test-model",
        config=CONFIG,
        revision="a" * 40,
    )
    publisher.start()
    feed = records.campaign_feed(live, project_root=root)
    assert feed["configured"] is True and len(feed["campaigns"]) == 1
    assert feed["campaigns"][0]["segment_id"] == "segment-000002"
    bundle["campaigns"][0]["updated_at"] = "2099-01-01T00:00:00+00:00"
    path.write_text(json.dumps(bundle))
    assert (
        records.campaign_feed(live, project_root=root)["campaigns"][0]["publication"]
        == "versioned_snapshot"
    )
    bundle["campaigns"][0]["code_revision"] = "b" * 40
    path.write_text(json.dumps(bundle))
    with pytest.raises(ValueError, match="identities disagree"):
        records.campaign_feed(live, project_root=root)

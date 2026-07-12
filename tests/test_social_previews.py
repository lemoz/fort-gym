from __future__ import annotations

from datetime import datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image


PUBLIC_PAGES = {
    "web/landing.html": ("/", "https://fortgym.live/", "home.png"),
    "web/worlds.html": ("/worlds", "https://fortgym.live/worlds", "worlds.png"),
    "web/results.html": ("/results", "https://fortgym.live/results", "results.png"),
    "web/protocols.html": (
        "/protocols",
        "https://fortgym.live/protocols",
        "protocols.png",
    ),
    "web/findings.html": ("/findings", "https://fortgym.live/findings", "findings.png"),
    "web/index.html": ("/live", "https://fortgym.live/live", "live.png"),
    "web/leaderboard.html": (
        "/leaderboard",
        "https://fortgym.live/leaderboard",
        "archive.png",
    ),
}


def test_public_pages_have_complete_large_card_metadata() -> None:
    from fort_gym.bench.api.server import app

    client = TestClient(app)
    for filename, (route, canonical, image_name) in PUBLIC_PAGES.items():
        html = Path(filename).read_text(encoding="utf-8")
        response = client.get(route)

        assert response.status_code == 200
        assert response.text == html
        assert f'<link rel="canonical" href="{canonical}">' in html
        assert '<meta property="og:site_name" content="Fort Labs">' in html
        assert '<meta property="og:type" content="website">' in html
        assert '<meta property="og:image:width" content="1200">' in html
        assert '<meta property="og:image:height" content="630">' in html
        assert f"https://fortgym.live/static/social/{image_name}?v=1" in html
        assert '<meta name="twitter:card" content="summary_large_image">' in html
        assert 'name="twitter:image:alt"' in html
        assert "/static/brand/favicon.svg" in html
        assert "/static/brand/apple-touch-icon.png" in html


def test_checked_in_social_cards_have_platform_dimensions() -> None:
    card_hashes = set()
    for _filename, (_route, _canonical, image_name) in PUBLIC_PAGES.items():
        path = Path("web/static/social") / image_name
        with Image.open(path) as image:
            assert image.size == (1200, 630)
            assert image.format == "PNG"
            assert image.getpixel((10, 2)) == (185, 243, 74)
            assert image.getpixel((20, 200)) == (8, 11, 8)
            assert len(image.getcolors(maxcolors=1_000_000) or []) > 20
        card_hashes.add(hashlib.sha256(path.read_bytes()).hexdigest())
    assert len(card_hashes) == len(PUBLIC_PAGES)

    with Image.open("web/static/brand/apple-touch-icon.png") as icon:
        assert icon.size == (180, 180)
    with Image.open("web/static/brand/favicon-32.png") as icon:
        assert icon.size == (32, 32)

    assert {
        path.name for path in Path("web/static/social").glob("fort-eval-*.png")
    } == {
        "fort-eval-easy-v1.png",
        "fort-eval-hard-v1.png",
        "fort-eval-discovery-v1.png",
    }
    for path in Path("web/static/social").glob("fort-eval-*.png"):
        with Image.open(path) as image:
            assert image.size == (1200, 630)


def test_replay_card_distinguishes_run_progress_from_recorded_frame(
    monkeypatch,
) -> None:
    from fort_gym.bench.api import social_cards

    captured = {}

    def capture(**fields):
        captured.update(fields)
        return b"png"

    monkeypatch.setattr(social_cards, "render_social_card", capture)
    run = SimpleNamespace(
        model="dfhack-governed-llm-glm5v",
        status="completed",
        step=100,
        max_steps=100,
        seed_save="seed_region1_fresh",
        evaluation_protocol="fort-eval-easy-v1",
    )

    assert (
        social_cards.render_run_social_card(
            run,
            {"step": 63, "screen_status": "recorded", "screen_text": "real frame"},
        )
        == b"png"
    )
    assert captured["marker_detail"].startswith("RUN 100/100 · FRAME 63")
    assert captured["screen_text"] == "real frame"


def test_static_evidence_frame_matches_provenance_manifest() -> None:
    social_dir = Path("web/static/social")
    provenance = json.loads(
        (social_dir / "provenance.json").read_text(encoding="utf-8")
    )
    frame = (social_dir / "first-g4-pass-screen.txt").read_text(encoding="utf-8")

    assert provenance["source_replay_token"] == "qw8S-Wmf53DYLESSrgCWGvLPvY2n0IuH"
    assert provenance["frame_step"] == 63
    assert provenance["frame_field"] == "screen_text"
    assert provenance["source_trace_bytes"] == 7_620_212
    assert len(provenance["source_trace_sha256"]) == 64
    assert (
        hashlib.sha256(frame.rstrip("\n").encode()).hexdigest()
        == provenance["frame_sha256"]
    )


def _public_replay(tmp_path: Path, *, model: str = "dfhack-governed-llm-glm5v"):
    from fort_gym.bench.run.storage import RUN_REGISTRY

    run = RUN_REGISTRY.create(
        backend="dfhack",
        model=model,
        max_steps=100,
        ticks_per_step=1000,
        seed_save="seed_region1_fresh",
        evaluation_protocol="fort-eval-easy-v1",
    )
    share = RUN_REGISTRY.create_share(run.run_id, scope=["replay", "export"])
    RUN_REGISTRY.set_status(run.run_id, status="completed", ended_at=datetime.utcnow())
    run_dir = tmp_path / run.run_id
    run_dir.mkdir()
    (run_dir / "trace.jsonl").write_text(
        '{"step":99,"screen_text":"#*PAUSED* Dwarf Fortress\\n# real recorded frame #"}\n',
        encoding="utf-8",
    )
    return run, share


def test_replay_permalink_has_run_specific_crawler_metadata(
    tmp_path, monkeypatch
) -> None:
    from fort_gym.bench.api import server
    from fort_gym.bench.run.storage import RUN_REGISTRY

    RUN_REGISTRY.reset_for_tests()
    monkeypatch.setattr(server, "ARTIFACTS_ROOT", tmp_path)
    try:
        run, share = _public_replay(tmp_path)

        response = TestClient(server.app).get(f"/r/{share.token}")

        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store, max-age=0"
        assert "GLM-5V Dwarf Fortress Replay | Fort Labs" in response.text
        assert f"https://fortgym.live/r/{share.token}" in response.text
        assert (
            f"https://fortgym.live/public/runs/{share.token}/social-card.png?v=1"
            in response.text
        )
        assert "run progress 99/100" in response.text
        assert "pictured recorded frame is step 99" in response.text
        assert "seed_region1_fresh" in response.text
        assert response.text.count("<!-- SOCIAL_META_START -->") == 1
        assert response.text.count("<!-- SOCIAL_META_END -->") == 1

        legacy = TestClient(server.app).get(
            f"/replay/{share.token}", follow_redirects=False
        )
        assert legacy.status_code == 308
        assert legacy.headers["location"] == f"/r/{share.token}"
        assert run.run_id not in response.text
    finally:
        RUN_REGISTRY.reset_for_tests()


def test_replay_metadata_escapes_public_model_text(tmp_path, monkeypatch) -> None:
    from fort_gym.bench.api import server
    from fort_gym.bench.run.storage import RUN_REGISTRY

    RUN_REGISTRY.reset_for_tests()
    monkeypatch.setattr(server, "ARTIFACTS_ROOT", tmp_path)
    try:
        _run, share = _public_replay(tmp_path, model='agent"><script>alert(1)</script>')

        response = TestClient(server.app).get(f"/r/{share.token}")

        assert response.status_code == 200
        assert "<script>alert(1)</script>" not in response.text
        assert "agent&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    finally:
        RUN_REGISTRY.reset_for_tests()


def test_public_run_social_card_uses_bounded_recorded_frame(
    tmp_path, monkeypatch
) -> None:
    from fort_gym.bench.api import server
    from fort_gym.bench.run.storage import RUN_REGISTRY

    RUN_REGISTRY.reset_for_tests()
    monkeypatch.setattr(server, "ARTIFACTS_ROOT", tmp_path)
    try:
        _run, share = _public_replay(tmp_path)
        client = TestClient(server.app)

        response = client.get(f"/public/runs/{share.token}/social-card.png")

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "private, no-store, max-age=0"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["etag"].startswith('"')
        with Image.open(BytesIO(response.content)) as image:
            assert image.size == (1200, 630)
            assert image.format == "PNG"

        cached = client.get(
            f"/public/runs/{share.token}/social-card.png",
            headers={"If-None-Match": response.headers["etag"]},
        )
        assert cached.status_code == 304
        assert cached.content == b""
        assert cached.headers["cache-control"] == "private, no-store, max-age=0"
    finally:
        RUN_REGISTRY.reset_for_tests()


def test_social_card_missing_frame_is_explicit_and_private_shares_fail_closed(
    tmp_path, monkeypatch
) -> None:
    from fort_gym.bench.api import server
    from fort_gym.bench.run.storage import RUN_REGISTRY

    RUN_REGISTRY.reset_for_tests()
    monkeypatch.setattr(server, "ARTIFACTS_ROOT", tmp_path)
    try:
        replay = RUN_REGISTRY.create(
            backend="dfhack",
            model="fake",
            max_steps=1,
            ticks_per_step=10,
        )
        replay_share = RUN_REGISTRY.create_share(
            replay.run_id, scope=["replay", "export"]
        )
        replay_only_share = RUN_REGISTRY.create_share(replay.run_id, scope=["replay"])
        private_share = RUN_REGISTRY.create_share(replay.run_id, scope=["live"])
        client = TestClient(server.app)

        explicit_gap = client.get(f"/public/runs/{replay_share.token}/social-card.png")
        assert explicit_gap.status_code == 200
        with Image.open(BytesIO(explicit_gap.content)) as image:
            assert image.size == (1200, 630)

        for path in (
            f"/r/{private_share.token}",
            f"/replay/{private_share.token}",
            f"/public/runs/{private_share.token}/social-card.png",
            f"/r/{replay_only_share.token}",
            f"/replay/{replay_only_share.token}",
            f"/public/runs/{replay_only_share.token}/social-card.png",
            "/r/not-a-real-token",
            "/public/runs/not-a-real-token/social-card.png",
        ):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 404
            assert replay.run_id not in response.text
    finally:
        RUN_REGISTRY.reset_for_tests()


def test_protocol_detail_has_protocol_specific_crawler_metadata() -> None:
    from fort_gym.bench.api.server import app

    response = TestClient(app).get("/protocols/fort-eval-hard-v1")

    assert response.status_code == 200
    assert "Fort-Eval Hard Protocol | Fort Labs" in response.text
    assert 'href="https://fortgym.live/protocols/fort-eval-hard-v1"' in response.text
    assert "Planned fixed-pixel and primitive-input profile" in response.text
    assert (
        "https://fortgym.live/static/social/fort-eval-hard-v1.png?v=1" in response.text
    )
    assert "document.title = socialTitle?.content" in response.text

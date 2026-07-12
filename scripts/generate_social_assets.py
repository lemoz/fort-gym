#!/usr/bin/env python3
"""Generate checked-in Fort Labs social cards and application icons."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from fort_gym.bench.api.social_cards import load_font, render_social_card, write_png


ROOT = Path(__file__).resolve().parents[1]
SOCIAL_DIR = ROOT / "web" / "static" / "social"
BRAND_DIR = ROOT / "web" / "static" / "brand"
FRAME = (SOCIAL_DIR / "first-g4-pass-screen.txt").read_text(encoding="utf-8")

CARDS = {
    "home.png": {
        "title": "Can an AI build a civilization that lasts?",
        "eyebrow": "FORT-EVAL / DWARF FORTRESS",
        "description": "Watch long-horizon agents build, adapt, and survive in real worlds.",
        "marker_title": "FIRST G4 PASS",
        "marker_detail": "100 steps · 2 functional rooms · population 7/7",
    },
    "worlds.png": {
        "title": "See what each model builds.",
        "eyebrow": "RECORDED WORLDS",
        "description": "Every public run opens into its recorded gameplay.",
        "marker_title": "PUBLIC REPLAYS",
        "marker_detail": "Real runs · bounded previews · complete traces",
    },
    "results.png": {
        "title": "Compare agents under declared protocols.",
        "eyebrow": "FORT-EVAL RESULTS",
        "description": "Every published result leads back to recorded play.",
        "marker_title": "PROTOCOL-SCOPED",
        "marker_detail": "Comparable runs only · evidence attached",
    },
    "protocols.png": {
        "title": "The rules agents play by.",
        "eyebrow": "FORT-EVAL PROTOCOLS",
        "description": "Declared observations, actions, knowledge, evidence, and ranking.",
        "marker_title": "EASY · HARD · DISCOVERY",
        "marker_detail": "Three interfaces · one living world",
    },
    "fort-eval-easy-v1.png": {
        "title": "Fort-Eval Easy",
        "eyebrow": "PROTOCOL / EASY",
        "description": "Governed structured state and bounded legal semantic DFHack controls.",
        "marker_title": "ACTIVE PILOT",
        "marker_detail": "Structured observation · semantic actions",
    },
    "fort-eval-hard-v1.png": {
        "title": "Fort-Eval Hard",
        "eyebrow": "PROTOCOL / HARD",
        "description": "Fixed-pixel perception and primitive human inputs in a three-dimensional world.",
        "marker_title": "PLANNED",
        "marker_detail": "Active perception · navigation · spatial memory",
    },
    "fort-eval-discovery-v1.png": {
        "title": "Fort-Eval Discovery",
        "eyebrow": "PROTOCOL / DISCOVERY",
        "description": "Transfer and discovery under controlled information limits.",
        "marker_title": "RESEARCH HORIZON",
        "marker_detail": "Held-out worlds · bounded learner state",
    },
    "findings.png": {
        "title": "What agents reveal when the world keeps pushing back.",
        "eyebrow": "RESEARCH NOTE 001",
        "description": "Seven findings from real Dwarf Fortress agent runs.",
        "marker_title": "G0-G4 PASSED",
        "marker_detail": "G5 failed · G6 open · G7 open",
    },
    "live.png": {
        "title": "Watch an agent play Dwarf Fortress.",
        "eyebrow": "FORT-EVAL LIVE",
        "description": "Live when a run is active. Recorded worlds remain available.",
        "marker_title": "LIVE VIEWER",
        "marker_detail": "Real game state · real actions · real simulation",
    },
    "archive.png": {
        "title": "The historical Fort-Eval archive.",
        "eyebrow": "HISTORICAL DASHBOARD",
        "description": "Earlier runs remain inspectable across scoring eras.",
        "marker_title": "ARCHIVE",
        "marker_detail": "Historical scores · public replay evidence",
    },
}


def _font(size: int) -> ImageFont.ImageFont:
    return load_font(size, mono=True, bold=True)


def _write_icons() -> None:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    for size, filename in ((32, "favicon-32.png"), (180, "apple-touch-icon.png")):
        image = Image.new("RGB", (size, size), "#071009")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, size, max(2, size // 14)), fill="#b9f34a")
        font = _font(max(16, int(size * 0.55)))
        label = "F"
        bbox = draw.textbbox((0, 0), label, font=font)
        draw.text(
            (
                (size - (bbox[2] - bbox[0])) / 2,
                (size - (bbox[3] - bbox[1])) / 2 - bbox[1],
            ),
            label,
            fill="#b9f34a",
            font=font,
        )
        image.save(BRAND_DIR / filename, format="PNG", optimize=True)


def main() -> None:
    for filename, fields in CARDS.items():
        write_png(
            SOCIAL_DIR / filename,
            render_social_card(screen_text=FRAME, **fields),
        )
    _write_icons()


if __name__ == "__main__":
    main()

"""Deterministic Fort Labs social-card rendering."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageFont


CARD_WIDTH = 1200
CARD_HEIGHT = 630
CARD_VERSION = "1"

_INK = "#f3f5ef"
_MUTED = "#a8b1a9"
_ACID = "#b9f34a"
_GAME = "#6fde8e"
_BACKGROUND = "#071009"
_PANEL = "#080b08"
_LINE = "#344639"

_MODEL_LABELS = {
    "dfhack-governed-llm-glm5v": "GLM-5V",
    "dfhack-governed-llm-gpt55": "GPT-5.5",
    "dfhack-governed-llm-gpt55-vision": "GPT-5.5 Vision",
    "dfhack-governed-llm-glm52": "GLM-5.2",
    "dfhack-governed-llm-fable5": "Fable",
    "anthropic/claude-fable-5": "Fable",
    "dfhack-governed-llm-gpt56-sol": "Sol",
    "openai/gpt-5.6-sol": "Sol",
    "dfhack-governed-llm-minimax-canary": "MiniMax M3 canary",
    "dfhack-governed-scripted": "Scripted baseline",
    "fake": "Mock agent",
}


def public_model_label(model: str) -> str:
    """Return a concise label without inventing a model identity."""

    normalized = str(model or "").strip()
    label = _MODEL_LABELS.get(normalized, normalized or "Unknown model")
    return f"{label[:47]}…" if len(label) > 48 else label


def load_font(
    size: int, *, mono: bool = False, bold: bool = False
) -> ImageFont.FreeTypeFont:
    """Load the shared card font consistently in runtime and asset generation."""

    family = "DejaVuSansMono" if mono else "DejaVuSans"
    filename = f"{family}{'-Bold' if bold else ''}.ttf"
    candidates = [
        filename,
        f"/usr/share/fonts/truetype/dejavu/{filename}",
        f"/opt/homebrew/share/fonts-dejavu/{filename}",
        f"/usr/local/share/fonts/{filename}",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _wrapped_lines(text: str, *, width: int, font: ImageFont.ImageFont) -> list[str]:
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    words = str(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or draw.textlength(candidate, font=font) <= width:
            current = candidate
            continue
        lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def _draw_screen(draw: ImageDraw.ImageDraw, screen_text: str | None) -> None:
    if not screen_text or not screen_text.strip():
        label_font = load_font(23, mono=True, bold=True)
        detail_font = load_font(16, mono=True)
        draw.text((744, 270), "FRAME NOT RECORDED", fill=_GAME, font=label_font)
        draw.text(
            (744, 310),
            "Replay metadata remains available.",
            fill=_MUTED,
            font=detail_font,
        )
        return

    font = load_font(16, mono=True, bold=True)
    lines = screen_text.replace("\r", "").splitlines()[:25]
    y = 24
    for line in lines:
        draw.text((340, y), line[:100], fill=_GAME, font=font)
        y += 19


def render_social_card(
    *,
    title: str,
    eyebrow: str,
    description: str,
    marker_title: str,
    marker_detail: str,
    screen_text: str | None,
    right_label: str = "RECORDED GAMEPLAY",
) -> bytes:
    """Render the approved 1200x630 Fort Labs social-card system."""

    image = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), _BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, CARD_WIDTH, 7), fill=_ACID)
    _draw_screen(draw, screen_text)

    draw.rectangle((0, 8, 599, CARD_HEIGHT), fill=_PANEL, outline=_LINE)
    draw.text((47, 51), "FORT", fill=_ACID, font=load_font(24, mono=True, bold=True))
    draw.text((120, 51), "LABS", fill=_INK, font=load_font(24, mono=True, bold=True))
    draw.text(
        (47, 171), eyebrow.upper(), fill=_ACID, font=load_font(15, mono=True, bold=True)
    )

    title_size = 57 if len(title) <= 48 else 47 if len(title) <= 68 else 41
    title_font = load_font(title_size, bold=True)
    title_lines = _wrapped_lines(title, width=505, font=title_font)[:4]
    title_y = 210
    title_spacing = title_size + 4
    for index, line in enumerate(title_lines):
        draw.text(
            (47, title_y + index * title_spacing), line, fill=_INK, font=title_font
        )

    description_y = title_y + len(title_lines) * title_spacing + 20
    description_font = load_font(20)
    for index, line in enumerate(
        _wrapped_lines(description, width=485, font=description_font)[:2]
    ):
        draw.text(
            (47, description_y + index * 29), line, fill=_MUTED, font=description_font
        )

    draw.line((47, 550, 554, 550), fill=_LINE, width=1)
    draw.text(
        (47, 577),
        "REAL PLAY · RECORDED EVIDENCE",
        fill=_ACID,
        font=load_font(14, mono=True, bold=True),
    )
    domain_font = load_font(14, mono=True, bold=True)
    domain = "fortgym.live"
    domain_width = draw.textlength(domain, font=domain_font)
    draw.text((554 - domain_width, 577), domain, fill=_INK, font=domain_font)

    label_font = load_font(13, mono=True, bold=True)
    label_width = draw.textlength(right_label, font=label_font)
    label_left = CARD_WIDTH - 35 - label_width - 24
    draw.rectangle((label_left, 34, CARD_WIDTH - 35, 69), fill=_ACID)
    draw.text((label_left + 12, 45), right_label, fill=_BACKGROUND, font=label_font)

    draw.rectangle((805, 492, 1165, 595), fill=_PANEL, outline="#4e6654")
    draw.text(
        (825, 513),
        marker_title.upper(),
        fill=_ACID,
        font=load_font(17, mono=True, bold=True),
    )
    marker_font = load_font(14, mono=True)
    marker_lines = _wrapped_lines(marker_detail, width=320, font=marker_font)[:2]
    for index, line in enumerate(marker_lines):
        draw.text((825, 542 + index * 22), line, fill=_MUTED, font=marker_font)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def render_run_social_card(run: Any, preview: Mapping[str, Any]) -> bytes:
    """Render one public replay card from its public metadata and bounded frame."""

    model = public_model_label(str(getattr(run, "model", "")))
    status = str(getattr(run, "status", "unknown")).replace("_", " ").upper()
    record_step = int(getattr(run, "step", 0) or 0)
    preview_step = preview.get("step")
    frame_step = preview_step if isinstance(preview_step, int) else None
    run_step = max(record_step, frame_step) if frame_step is not None else record_step
    max_steps = int(getattr(run, "max_steps", 0) or 0)
    seed = str(getattr(run, "seed_save", "") or "seed not reported")
    protocol = str(getattr(run, "evaluation_protocol", "") or "exploratory run")
    run_detail = f"RUN {run_step}/{max_steps}" if max_steps else f"RUN {run_step}"
    frame_detail = (
        f"FRAME {frame_step}" if frame_step is not None else "FRAME NOT RECORDED"
    )
    return render_social_card(
        title=model,
        eyebrow="RECORDED RUN / DWARF FORTRESS",
        description=f"{status.title()} on {seed}. Open the replay to inspect every recorded decision.",
        marker_title=status,
        marker_detail=f"{run_detail} · {frame_detail} · {protocol}",
        screen_text=preview.get("screen_text")
        if preview.get("screen_status") == "recorded"
        else None,
    )


def write_png(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


__all__ = [
    "CARD_HEIGHT",
    "CARD_VERSION",
    "CARD_WIDTH",
    "load_font",
    "public_model_label",
    "render_run_social_card",
    "render_social_card",
    "write_png",
]

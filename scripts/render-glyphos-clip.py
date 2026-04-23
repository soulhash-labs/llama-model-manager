#!/usr/bin/env python3
"""Render a short GlyphOS encoding demo GIF for social posts."""

from __future__ import annotations

import math
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError as exc:  # pragma: no cover - operator guidance path
    raise SystemExit(
        "Pillow is required to render this asset. Run: python3 -m pip install pillow"
    ) from exc

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "branding"
GIF_PATH = OUT_DIR / "glyphos-encoding-demo.gif"
POSTER_PATH = OUT_DIR / "glyphos-encoding-demo-poster.png"

WIDTH = 1280
HEIGHT = 720
FPS = 12
FRAMES = 72
SCALE = 1

COLORS = {
    "ink": (18, 29, 37),
    "muted": (86, 99, 107),
    "panel": (252, 249, 240),
    "panel_2": (245, 238, 224),
    "line": (202, 190, 168),
    "blue": (21, 99, 255),
    "blue_soft": (93, 151, 255),
    "green": (16, 150, 112),
    "amber": (230, 142, 36),
    "rose": (215, 73, 103),
    "white": (255, 255, 255),
    "black": (0, 0, 0),
}

GLYPHS = ["RA", "SE", "NO", "VE", "LO", "FI", "KA", "OM", "TI", "QO", "AI", "MU"]
SOURCE_LINES = [
    "Summarize this local codebase",
    "preserve private context",
    "route through llama.cpp",
    "optimize long-run transport",
    "return actionable edits",
]
TOOL_LINES = ["Claude Code", "OpenClaw", "opencode", "GlyphOS AI Compute"]


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        f"/usr/share/fonts/truetype/dejavu/{name}.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


FONT_TITLE = font("DejaVuSans-Bold", 44)
FONT_H2 = font("DejaVuSans-Bold", 30)
FONT_BODY = font("DejaVuSans", 24)
FONT_SMALL = font("DejaVuSans", 18)
FONT_TINY = font("DejaVuSans", 15)
FONT_MONO = font("DejaVuSansMono", 20)
FONT_MONO_BOLD = font("DejaVuSansMono-Bold", 26)


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def color_lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(lerp(x, y, t)) for x, y in zip(a, b))


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill, outline=None, width=1) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def shadowed_panel(img: Image.Image, box: tuple[int, int, int, int], radius: int = 28) -> ImageDraw.ImageDraw:
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    x1, y1, x2, y2 = box
    sd.rounded_rectangle((x1 + 10, y1 + 16, x2 + 10, y2 + 16), radius=radius, fill=(31, 45, 55, 34))
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    img.alpha_composite(shadow)
    draw = ImageDraw.Draw(img)
    rounded(draw, box, radius, COLORS["panel"], COLORS["line"], 2)
    return draw


def text_center(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font_obj, fill) -> None:
    bbox = draw.textbbox((0, 0), text, font=font_obj)
    draw.text((xy[0] - (bbox[2] - bbox[0]) / 2, xy[1] - (bbox[3] - bbox[1]) / 2), text, font=font_obj, fill=fill)


def build_base_background() -> Image.Image:
    img = Image.new("RGBA", (WIDTH, HEIGHT), COLORS["panel_2"] + (255,))
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        t = y / HEIGHT
        base = color_lerp((250, 246, 232), (226, 237, 238), t)
        draw.line((0, y, WIDTH, y), fill=base + (255,))

    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((760, -160, 1440, 450), fill=(207, 224, 255, 82))
    gd.ellipse((-180, 410, 440, 880), fill=(244, 205, 139, 55))
    glow = glow.filter(ImageFilter.GaussianBlur(54))
    img.alpha_composite(glow)
    return img


BASE_BACKGROUND = build_base_background()


def make_background(frame_index: int) -> Image.Image:
    img = BASE_BACKGROUND.copy()
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for i in range(16):
        x = -120 + i * 96 + int(10 * math.sin(frame_index * 0.08 + i))
        d.line((x, -20, x + 230, HEIGHT + 30), fill=(21, 99, 255, 14), width=2)
    img.alpha_composite(overlay)
    return img


def draw_header(draw: ImageDraw.ImageDraw) -> None:
    draw.text((70, 44), "GlyphOS AI Compute", font=FONT_TITLE, fill=COLORS["ink"])
    draw.text((72, 100), "compact glyph encoding for local llama.cpp routing", font=FONT_BODY, fill=COLORS["muted"])
    rounded(draw, (1012, 50, 1210, 100), 20, (18, 29, 37), None)
    text_center(draw, (1111, 75), "LOCAL ONLY", FONT_SMALL, COLORS["white"])


def draw_payload_panel(img: Image.Image, progress: float) -> None:
    draw = shadowed_panel(img, (68, 150, 526, 576))
    draw.text((102, 184), "Verbose request", font=FONT_H2, fill=COLORS["ink"])
    draw.text((104, 223), "source payload", font=FONT_SMALL, fill=COLORS["muted"])

    reveal = ease(min(1.0, progress * 1.25))
    for idx, line in enumerate(SOURCE_LINES):
        y = 278 + idx * 45
        alpha = int(255 * max(0.2, 1 - progress * 0.65))
        draw.text((106, y), f"{idx + 1:02d}", font=FONT_MONO, fill=(145, 137, 122, alpha))
        chars = int(len(line) * reveal)
        draw.text((154, y), line[:chars], font=FONT_MONO, fill=COLORS["ink"] + (alpha,))

    draw.text((106, 514), "token payload", font=FONT_SMALL, fill=COLORS["muted"])
    tokens = int(12480 - 10570 * ease(progress))
    draw.text((308, 500), f"{tokens:,}", font=FONT_MONO_BOLD, fill=COLORS["rose"])


def draw_glyph_panel(img: Image.Image, progress: float) -> None:
    draw = shadowed_panel(img, (754, 150, 1212, 576))
    draw.text((788, 184), "Glyph encoded", font=FONT_H2, fill=COLORS["ink"])
    draw.text((790, 223), "routed to active local endpoint", font=FONT_SMALL, fill=COLORS["muted"])

    p = ease(max(0.0, min(1.0, (progress - 0.18) / 0.62)))
    for i, glyph in enumerate(GLYPHS):
        row = i // 4
        col = i % 4
        x = int(796 + col * 94)
        y = int(280 + row * 70)
        local = ease(max(0.0, min(1.0, p * 1.35 - i * 0.055)))
        w = int(64 + 14 * local)
        h = int(42 + 5 * local)
        fill = color_lerp((235, 230, 216), (21, 99, 255), local)
        txt = color_lerp(COLORS["muted"], COLORS["white"], local)
        rounded(draw, (x, y, x + w, y + h), 16, fill, None)
        text_center(draw, (x + w // 2, y + h // 2), glyph, FONT_MONO_BOLD, txt)

    draw.text((790, 508), "encoded payload", font=FONT_SMALL, fill=COLORS["muted"])
    encoded = int(1910 + 120 * math.sin(progress * math.tau))
    draw.text((1004, 494), f"{encoded:,}", font=FONT_MONO_BOLD, fill=COLORS["green"])


def draw_transport(img: Image.Image, progress: float, frame_index: int) -> None:
    draw = ImageDraw.Draw(img)
    x1, y1, x2, y2 = 542, 322, 738, 322
    draw.line((x1, y1, x2, y2), fill=(21, 99, 255, 88), width=7)
    draw.polygon([(x2, y2), (x2 - 22, y2 - 13), (x2 - 22, y2 + 13)], fill=(21, 99, 255, 150))

    p = ease(max(0.0, min(1.0, (progress - 0.08) / 0.72)))
    for i in range(7):
        t = (p + i * 0.14 + frame_index * 0.018) % 1.0
        x = int(lerp(x1 + 12, x2 - 34, t))
        y = int(y1 + math.sin((t * math.tau) + i) * 12)
        r = 5 + int(4 * math.sin((frame_index + i) * 0.25) ** 2)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(21, 99, 255, 160))

    meter_p = ease(max(0.0, min(1.0, (progress - 0.38) / 0.38)))
    rounded(draw, (548, 390, 730, 476), 24, (255, 255, 255, 210), (202, 190, 168), 1)
    text_center(draw, (639, 416), "60-90%", FONT_MONO_BOLD, COLORS["green"])
    text_center(draw, (639, 450), "payload drop", FONT_SMALL, COLORS["muted"])
    if meter_p > 0:
        rounded(draw, (566, 490, 712, 506), 8, (222, 229, 226), None)
        rounded(draw, (566, 490, int(712 - 112 * meter_p), 506), 8, COLORS["green"], None)


def draw_footer(draw: ImageDraw.ImageDraw, progress: float) -> None:
    p = ease(max(0.0, min(1.0, (progress - 0.68) / 0.28)))
    y = int(584 - 16 * p)
    rounded(draw, (250, y, 1030, y + 62), 24, (18, 29, 37), None)
    text_center(draw, (640, y + 31), "GlyphOS -> llama.cpp  http://127.0.0.1:8081/v1", FONT_MONO, COLORS["white"])

    label_alpha = int(255 * p)
    for i, tool in enumerate(TOOL_LINES):
        x = 268 + i * 190
        rounded(draw, (x, y + 78, x + 164, y + 116), 15, (255, 255, 255, 210), (202, 190, 168), 1)
        text_center(draw, (x + 82, y + 97), tool, FONT_TINY, COLORS["ink"] + (label_alpha,))


def draw_frame(frame_index: int) -> Image.Image:
    progress = frame_index / (FRAMES - 1)
    img = make_background(frame_index)
    draw = ImageDraw.Draw(img)
    draw_header(draw)
    draw_payload_panel(img, progress)
    draw_transport(img, progress, frame_index)
    draw_glyph_panel(img, progress)
    draw_footer(draw, progress)

    if frame_index > FRAMES - 13:
        fade = int(170 * (frame_index - (FRAMES - 13)) / 12)
        overlay = Image.new("RGBA", img.size, (252, 249, 240, fade))
        img.alpha_composite(overlay)
        d = ImageDraw.Draw(img)
        text_center(d, (640, 328), "Stay local. Stay private. Stay fast.", FONT_TITLE, COLORS["ink"])
        text_center(d, (640, 384), "llama-model-manager + GlyphOS AI Compute", FONT_BODY, COLORS["blue"])
    return img.convert("RGB")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frames = [draw_frame(i) for i in range(FRAMES)]
    frames[48].save(POSTER_PATH)
    frames[0].save(
        GIF_PATH,
        save_all=True,
        append_images=frames[1:],
        duration=int(1000 / FPS),
        loop=0,
        optimize=True,
    )
    print(f"wrote {GIF_PATH}")
    print(f"wrote {POSTER_PATH}")


if __name__ == "__main__":
    main()

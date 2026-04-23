#!/usr/bin/env python3
"""Render the Sovereignty Bridge branding GIF."""

from __future__ import annotations

import math
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Pillow is required. Run: python3 -m pip install pillow") from exc

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "branding"
GIF_PATH = OUT_DIR / "sovereignty-bridge.gif"
POSTER_PATH = OUT_DIR / "sovereignty-bridge-poster.png"

WIDTH = 960
HEIGHT = 540
FPS = 10
FRAMES = 200

COLORS = {
    "bg0": (8, 13, 22),
    "bg1": (13, 21, 34),
    "panel": (14, 24, 38),
    "panel2": (18, 31, 49),
    "line": (52, 79, 111),
    "ink": (235, 242, 250),
    "muted": (137, 157, 180),
    "blue": (45, 146, 255),
    "cyan": (26, 220, 218),
    "purple": (154, 99, 255),
    "green": (33, 220, 145),
    "amber": (242, 176, 72),
    "red": (244, 92, 124),
    "white": (255, 255, 255),
}


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        f"/usr/share/fonts/truetype/dejavu/{name}.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


FONT_TITLE = font("DejaVuSans-Bold", 34)
FONT_H2 = font("DejaVuSans-Bold", 22)
FONT_BODY = font("DejaVuSans", 17)
FONT_SMALL = font("DejaVuSans", 13)
FONT_TINY = font("DejaVuSans", 11)
FONT_MONO = font("DejaVuSansMono", 15)
FONT_MONO_BOLD = font("DejaVuSansMono-Bold", 17)
FONT_BIG_MONO = font("DejaVuSansMono-Bold", 30)
FONT_FINAL = font("DejaVuSans-Bold", 42)


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def clamp(t: float) -> float:
    return max(0.0, min(1.0, t))


def phase(progress: float, start: float, end: float) -> float:
    return ease((progress - start) / (end - start))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(lerp(x, y, t)) for x, y in zip(a, b))


def text_center(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font_obj, fill) -> None:
    bbox = draw.textbbox((0, 0), text, font=font_obj)
    draw.text((xy[0] - (bbox[2] - bbox[0]) / 2, xy[1] - (bbox[3] - bbox[1]) / 2), text, font=font_obj, fill=fill)


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill, outline=None, width: int = 1) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def base_background(frame: int) -> Image.Image:
    img = Image.new("RGBA", (WIDTH, HEIGHT), COLORS["bg0"] + (255,))
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        t = y / HEIGHT
        draw.line((0, y, WIDTH, y), fill=mix(COLORS["bg0"], COLORS["bg1"], t) + (255,))
    grid = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    offset = frame % 28
    for x in range(-40, WIDTH + 40, 56):
        gd.line((x + offset, 0, x - 70 + offset, HEIGHT), fill=(45, 146, 255, 18), width=1)
    for y in range(32, HEIGHT, 54):
        gd.line((0, y, WIDTH, y), fill=(154, 99, 255, 12), width=1)
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gl = ImageDraw.Draw(glow)
    gl.ellipse((520, -160, 1120, 380), fill=(45, 146, 255, 58))
    gl.ellipse((-200, 240, 380, 700), fill=(154, 99, 255, 42))
    glow = glow.filter(ImageFilter.GaussianBlur(44))
    img.alpha_composite(grid)
    img.alpha_composite(glow)
    return img


def panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str, accent) -> None:
    rounded(draw, box, 22, COLORS["panel"], COLORS["line"], 1)
    x1, y1, x2, _ = box
    rounded(draw, (x1 + 16, y1 + 16, x1 + 28, y1 + 28), 6, accent, None)
    draw.text((x1 + 40, y1 + 10), title, font=FONT_H2, fill=COLORS["ink"])


def terminal_lines(progress: float) -> list[tuple[str, tuple[int, int, int]]]:
    lines: list[tuple[str, tuple[int, int, int]]] = []
    cmd = "llama-model claude-gateway start"
    type_p = phase(progress, 0.00, 0.12)
    typed = cmd[: int(len(cmd) * type_p)]
    lines.append((f"$ {typed}", COLORS["green"]))
    if progress > 0.13:
        lines.extend([
            ("status: running", COLORS["ink"]),
            ("url: http://127.0.0.1:4000", COLORS["cyan"]),
            ("upstream: http://127.0.0.1:8081/v1", COLORS["cyan"]),
        ])
    if progress > 0.18:
        explain = "/explain this entire repo"
        p = phase(progress, 0.18, 0.31)
        lines.append((f"claude-code> {explain[: int(len(explain) * p)]}", COLORS["purple"]))
    if progress > 0.32:
        stream = [
            "reading local repo graph...",
            "routing through local Anthropic gateway...",
            "tokens streaming from llama.cpp...",
            "no cloud handoff detected",
        ]
        count = min(len(stream), int((progress - 0.32) / 0.04) + 1)
        for line in stream[:count]:
            lines.append((f"  {line}", COLORS["muted"]))
    return lines[-10:]


def draw_terminal(draw: ImageDraw.ImageDraw, progress: float) -> None:
    box = (32, 86, 464, 416)
    panel(draw, box, "claude-code terminal", COLORS["purple"])
    x1, y1, x2, _ = box
    draw.line((x1 + 16, y1 + 48, x2 - 16, y1 + 48), fill=COLORS["line"], width=1)
    lines = terminal_lines(progress)
    for idx, (line, fill) in enumerate(lines):
        draw.text((x1 + 22, y1 + 66 + idx * 25), line, font=FONT_MONO, fill=fill)
    if 0.32 < progress < 0.74:
        dots = "." * (1 + (int(progress * 60) % 3))
        draw.text((x1 + 22, 378), f"local reasoning{dots}", font=FONT_MONO_BOLD, fill=COLORS["green"])


def stat_bar(draw: ImageDraw.ImageDraw, xy: tuple[int, int], label: str, value: float, color) -> None:
    x, y = xy
    draw.text((x, y), label, font=FONT_TINY, fill=COLORS["muted"])
    rounded(draw, (x, y + 18, x + 150, y + 28), 5, (28, 42, 61), None)
    rounded(draw, (x, y + 18, int(x + 150 * value), y + 28), 5, color, None)
    draw.text((x + 160, y + 10), f"{int(value * 100)}%", font=FONT_SMALL, fill=COLORS["ink"])


def draw_dashboard(draw: ImageDraw.ImageDraw, progress: float, frame: int) -> None:
    box = (496, 86, 928, 416)
    panel(draw, box, "llama-model-manager", COLORS["blue"])
    x1, y1, _, _ = box
    gateway_on = progress > 0.12
    health_on = progress > 0.18
    pulse = 0.5 + 0.5 * math.sin(frame * 0.32)
    status_color = COLORS["green"] if gateway_on else COLORS["red"]
    rounded(draw, (x1 + 24, y1 + 62, x1 + 386, y1 + 112), 16, COLORS["panel2"], COLORS["line"])
    draw.ellipse((x1 + 42, y1 + 78, x1 + 62, y1 + 98), fill=status_color)
    draw.text((x1 + 78, y1 + 72), "Claude Gateway", font=FONT_BODY, fill=COLORS["ink"])
    draw.text((x1 + 230, y1 + 72), "RUNNING" if gateway_on else "STOPPED", font=FONT_MONO_BOLD, fill=status_color)

    rounded(draw, (x1 + 24, y1 + 126, x1 + 386, y1 + 258), 18, COLORS["panel2"], COLORS["line"])
    draw.text((x1 + 42, y1 + 142), "Live local workload", font=FONT_BODY, fill=COLORS["ink"])
    if health_on:
        cpu = 0.38 + 0.19 * pulse
        gpu = 0.74 + 0.18 * math.sin(frame * 0.27 + 1) ** 2
        vram = 0.61 + 0.12 * math.sin(frame * 0.19 + 2) ** 2
    else:
        cpu = gpu = vram = 0.08
    stat_bar(draw, (x1 + 42, y1 + 178), "CPU", cpu, COLORS["cyan"])
    stat_bar(draw, (x1 + 42, y1 + 210), "GPU", gpu, COLORS["green"])
    stat_bar(draw, (x1 + 226, y1 + 210), "VRAM", vram, COLORS["amber"])

    rounded(draw, (x1 + 24, y1 + 272, x1 + 386, y1 + 312), 14, (10, 19, 31), COLORS["line"])
    model = "qwen-coder-local" if progress < 0.78 else "Gemma-4 E4B"
    draw.text((x1 + 42, y1 + 282), f"active model: {model}", font=FONT_MONO, fill=COLORS["cyan"])


def draw_bridge(draw: ImageDraw.ImageDraw, progress: float, frame: int) -> None:
    y = 445
    text_center(draw, (WIDTH // 2, 36), "The Sovereignty Bridge", FONT_TITLE, COLORS["ink"])
    text_center(draw, (WIDTH // 2, 66), "Claude Code -> local gateway -> llama.cpp -> GlyphOS routing", FONT_SMALL, COLORS["muted"])
    rounded(draw, (138, y, 822, y + 52), 26, (11, 20, 33), COLORS["line"])
    labels = ["Claude Code", "Gateway", "llama.cpp", "GlyphOS"]
    xs = [218, 382, 548, 710]
    active = min(3, int(max(0, progress - 0.11) / 0.18)) if progress > 0.11 else -1
    for idx, (label, x) in enumerate(zip(labels, xs)):
        color = COLORS["green"] if idx <= active else COLORS["muted"]
        draw.ellipse((x - 12, y + 14, x + 12, y + 38), fill=color)
        text_center(draw, (x, y + 76), label, FONT_TINY, color)
        if idx < len(xs) - 1:
            draw.line((x + 18, y + 26, xs[idx + 1] - 18, y + 26), fill=COLORS["blue"] if idx < active else COLORS["line"], width=3)
    if progress > 0.22:
        for i in range(4):
            t = (progress * 2.8 + i * 0.25 + frame * 0.006) % 1
            x = int(218 + (710 - 218) * t)
            draw.ellipse((x - 4, y + 22, x + 4, y + 30), fill=COLORS["cyan"])


def draw_glyph_overlay(img: Image.Image, progress: float) -> None:
    if not (0.50 <= progress <= 0.77):
        return
    p = phase(progress, 0.50, 0.58)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, int(95 * p)))
    img.alpha_composite(overlay)
    card = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)
    alpha = int(235 * p)
    rounded(draw, (246, 148, 714, 344), 30, (13, 21, 34, alpha), (45, 146, 255, alpha), 2)
    text_center(draw, (480, 198), "Ψ Glyph Encoding Active", FONT_H2, COLORS["white"] + (int(255 * p),))
    text_center(draw, (480, 244), "up to 90% payload reduction", FONT_BIG_MONO, COLORS["green"] + (int(255 * p),))
    text_center(draw, (480, 292), "LOCAL ROUTING  •  TRANSPORT SPEED", FONT_MONO, COLORS["cyan"] + (int(255 * p),))
    img.alpha_composite(card)


def draw_model_switch(draw: ImageDraw.ImageDraw, progress: float) -> None:
    if progress < 0.75:
        return
    p = phase(progress, 0.75, 0.83)
    x = int(690 - 18 * math.sin(p * math.pi))
    rounded(draw, (584, 176, 904, 278), 22, (11, 20, 33), COLORS["blue"], 2)
    draw.text((604, 192), "Model Switcher", font=FONT_BODY, fill=COLORS["ink"])
    draw.text((604, 224), "qwen-coder-local", font=FONT_MONO, fill=COLORS["muted"])
    draw.text((x, 224), "->", font=FONT_MONO_BOLD, fill=COLORS["green"])
    draw.text((744, 224), "Gemma-4 E4B", font=FONT_MONO_BOLD, fill=COLORS["cyan"])


def draw_final(img: Image.Image, progress: float) -> None:
    if progress < 0.86:
        return
    p = phase(progress, 0.86, 0.92)
    wash = Image.new("RGBA", img.size, (5, 10, 18, int(230 * p)))
    img.alpha_composite(wash)
    draw = ImageDraw.Draw(img)
    text_center(draw, (WIDTH // 2, 208), "IP: PROTECTED.", FONT_FINAL, COLORS["white"] + (int(255 * p),))
    text_center(draw, (WIDTH // 2, 266), "BRAIN: LOCAL.", FONT_FINAL, COLORS["green"] + (int(255 * p),))
    text_center(draw, (WIDTH // 2, 334), "soulhash.ai/downloads", FONT_BIG_MONO, COLORS["cyan"] + (int(255 * p),))
    text_center(draw, (WIDTH // 2, 386), "llama-model-manager", FONT_BODY, COLORS["muted"] + (int(255 * p),))


def draw_frame(frame: int) -> Image.Image:
    progress = frame / (FRAMES - 1)
    img = base_background(frame)
    draw = ImageDraw.Draw(img)
    draw_bridge(draw, progress, frame)
    draw_terminal(draw, progress)
    draw_dashboard(draw, progress, frame)
    draw_model_switch(draw, progress)
    draw_glyph_overlay(img, progress)
    draw_final(img, progress)
    return img.convert("RGB")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frames = [draw_frame(i) for i in range(FRAMES)]
    frames[128].save(POSTER_PATH)
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

#!/usr/bin/env python3
from __future__ import annotations

import base64
import io
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - environment dependent
    raise SystemExit("Pillow is required to render public assets.") from exc


ROOT = Path(__file__).resolve().parents[1]
WEB_APP = ROOT / "web" / "app.py"
SCREENSHOT_DIR = ROOT / "docs" / "screenshots"
DEMO_DIR = ROOT / "docs" / "demo"
BRANDING_DIR = ROOT / "docs" / "branding"
PORT = 8767
DEFAULT_WINDOW_SIZE = {"width": 1440, "height": 2200}
SOCIAL_CARD_WINDOW_SIZE = {"width": 1280, "height": 726}
SCREENSHOT_SCENARIOS = [
    ("dashboard-overview.png", f"http://127.0.0.1:{PORT}/", DEFAULT_WINDOW_SIZE),
    ("dashboard-serve-feedback.png", f"http://127.0.0.1:{PORT}/?scenario=serve", DEFAULT_WINDOW_SIZE),
    ("dashboard-scan-feedback.png", f"http://127.0.0.1:{PORT}/?scenario=scan", DEFAULT_WINDOW_SIZE),
    ("dashboard-empty-state.png", f"http://127.0.0.1:{PORT}/?scenario=empty", DEFAULT_WINDOW_SIZE),
]
BRANDING_SCENARIOS = [
    # Firefox headless reports screenshots at viewport size, so the outer window needs extra
    # vertical room to land on the standard 1280x640 social-preview export.
    ("llama-model-manager-social-card.png", f"http://127.0.0.1:{PORT}/social-card.html", SOCIAL_CARD_WINDOW_SIZE),
]


def wait_for_url(url: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=0.5).read()
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for {url}")


def webdriver_call(session_id: str, method: str, path: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:4444/session/{session_id}{path}",
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode())


def capture(url: str, output: Path, window_size: dict[str, int]) -> None:
    gecko = subprocess.Popen(
        ["/snap/bin/geckodriver", "--port", "4444"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_url("http://127.0.0.1:4444/status")
        payload = {
            "capabilities": {
                "alwaysMatch": {
                    "browserName": "firefox",
                    "moz:firefoxOptions": {"args": ["-headless"]},
                }
            }
        }
        request = urllib.request.Request(
            "http://127.0.0.1:4444/session",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            session_id = json.loads(response.read().decode())["value"]["sessionId"]

        webdriver_call(session_id, "POST", "/window/rect", window_size)
        webdriver_call(session_id, "POST", "/url", {"url": url})
        time.sleep(2.4)
        shot = webdriver_call(session_id, "GET", "/screenshot")["value"]
        output.write_bytes(base64.b64decode(shot))

        try:
            webdriver_call(session_id, "DELETE", "")
        except Exception:
            pass
    finally:
        gecko.terminate()
        try:
            gecko.wait(timeout=5)
        except Exception:
            gecko.kill()


def render_assets() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    BRANDING_DIR.mkdir(parents=True, exist_ok=True)

    server = subprocess.Popen(
        [sys.executable, str(WEB_APP), "--demo", "--no-browser", "--port", str(PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_url(f"http://127.0.0.1:{PORT}/healthz")

        frame_paths: list[Path] = []
        for filename, url, window_size in SCREENSHOT_SCENARIOS:
            destination = SCREENSHOT_DIR / filename
            capture(url, destination, window_size)
            frame_paths.append(destination)

        for filename, url, window_size in BRANDING_SCENARIOS:
            capture(url, BRANDING_DIR / filename, window_size)

        gif_frames = [Image.open(path).convert("P", palette=Image.ADAPTIVE) for path in frame_paths[:3]]
        gif_frames[0].save(
            DEMO_DIR / "llama-model-manager-demo.gif",
            save_all=True,
            append_images=gif_frames[1:],
            duration=[1800, 1800, 1800],
            loop=0,
            optimize=False,
        )
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()


if __name__ == "__main__":
    render_assets()

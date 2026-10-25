"""End to end: the built frontend against the real app and a fake YouTube, in Chrome.

Opt-in. Build the frontend first, then:

    RUN_BROWSER_TESTS=1 uv run --with playwright python -m pytest -m browser

It uses the installed Google Chrome; set PLAYWRIGHT_CHROMIUM_EXECUTABLE to use another
Chromium build.
"""

import os
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from app.config import config
from main import DIST, create_app
from tests import fake_youtube
from tests.fake_youtube import FakeYouTube

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Browser tests are opt-in"
    ),
]

VIDEO = "aircAruvnKk"
UPLOADS = ["upload00001", "upload00002"]


def sample_media(folder: Path) -> bytes:
    """Two seconds of real H.264/AAC, so the player can actually load it."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is needed to make a playable sample")
    path = folder / "sample.mp4"
    subprocess.run(
        [ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=0x334455:s=320x180:d=2",
         "-f", "lavfi", "-i", "sine=d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(path)],
        check=True,
        timeout=60,
    )  # fmt: skip
    return path.read_bytes()


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, FakeYouTube]]:
    if not (DIST / "index.html").is_file():
        pytest.skip("Build the frontend first: npm run build")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path / "media")
    monkeypatch.setattr(fake_youtube, "MEDIA", sample_media(tmp_path))
    youtube = FakeYouTube()
    youtube.add(
        VIDEO,
        "But what is a neural network?",
        chapters=[
            {"start_time": 0, "end_time": 1, "title": "Introduction example"},
            {"start_time": 1, "end_time": 2, "title": "Series preview"},
        ],
    )
    for youtube_id in UPLOADS:
        youtube.add(youtube_id, f"Upload {youtube_id[-1]}")
    youtube.tabs["video"] = UPLOADS
    app_server = uvicorn.Server(
        uvicorn.Config(create_app(youtube=youtube), log_config=None, lifespan="on")
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        thread = threading.Thread(
            target=app_server.run, kwargs={"sockets": [listener]}, daemon=True
        )
        thread.start()
        deadline = time.monotonic() + 10
        while not app_server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert app_server.started, "Server did not start"
        try:
            yield f"http://127.0.0.1:{port}", youtube
        finally:
            app_server.should_exit = True
            thread.join(timeout=15)


def test_setup_add_play_subscribe_and_settings(server) -> None:
    from playwright.sync_api import expect, sync_playwright

    base, _ = server
    executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=executable, channel=None if executable else "chrome"
        )
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base)

            page.get_by_label("Username").fill("owner")
            page.get_by_label("Password").fill("correct horse battery")
            page.get_by_role("button", name="Create account").click()

            page.get_by_role("button", name="Add", exact=True).click()
            dialog = page.get_by_role("dialog", name="Add from YouTube")
            dialog.get_by_label("YouTube URL").fill(f"https://youtu.be/{VIDEO}")
            dialog.get_by_role("button", name="Resolve").click()
            expect(dialog.get_by_text("But what is a neural network?")).to_be_visible()
            dialog.get_by_role("button", name="Options").click()
            dialog.get_by_label("Quality").select_option("720p")
            dialog.get_by_role("button", name="Add and download").click()
            expect(page.get_by_role("status").filter(has_text="Added")).to_be_visible()

            page.get_by_role("link", name="But what is a neural network?").first.click()
            page.wait_for_function(
                "() => { const v = document.querySelector('video'); return v && v.readyState >= 2 }",
                timeout=15000,
            )
            expect(page.get_by_text("Series preview").first).to_be_visible()

            page.goto(f"{base}/#/subscriptions")
            page.get_by_role("button", name="Add subscription").click()
            dialog.get_by_label("YouTube URL").fill("https://www.youtube.com/@fixture")
            dialog.get_by_role("button", name="Resolve").click()
            dialog.get_by_role("group", name="Download policy").get_by_role(
                "button", name="Everything"
            ).click()
            dialog.get_by_role("button", name="Subscribe").click()
            expect(page.get_by_role("status").filter(has_text="Subscribed")).to_be_visible()

            page.goto(f"{base}/#/library")
            for youtube_id in UPLOADS:
                expect(
                    page.get_by_role("link", name=f"Upload {youtube_id[-1]}").first
                ).to_be_visible(timeout=15000)

            page.goto(f"{base}/#/system")
            page.get_by_label("Default quality").select_option("720p")
            page.get_by_role("button", name="Save settings").click()
            expect(page.get_by_role("status").filter(has_text="Settings saved")).to_be_visible()

            page.set_viewport_size({"width": 375, "height": 812})
            page.goto(f"{base}/#/library")
            expect(page.get_by_role("link", name="Queue").last).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert not errors, errors
        finally:
            browser.close()

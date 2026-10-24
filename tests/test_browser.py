"""Browser integration test for first-run setup and subscription archiving."""

import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from app.api.endpoints import subscriptions
from app.core import downloader
from app.core.config import settings
from main import create_app
from tests import support

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Browser tests are opt-in"
    ),
]


def test_setup_subscription_filters_download_and_playback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from playwright.sync_api import sync_playwright

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is required for the playback fixture")
    video = tmp_path / "sample.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=navy:s=320x180:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(video),
        ],
        check=True,
        timeout=30,
    )
    monkeypatch.setattr(support, "MEDIA", video.read_bytes())
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "archive.db"))
    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "LOG_DIR", str(tmp_path / "logs"))
    source = support.FakeYouTube()
    source.entries_by_tab = {
        "videos": [support.VIDEO_ID],
        "shorts": [support.SECOND_ID],
        "streams": [],
    }
    monkeypatch.setattr(downloader, "get_ytdlp_service", lambda: source)
    monkeypatch.setattr(subscriptions, "get_ytdlp_service", lambda: source)
    server = uvicorn.Server(uvicorn.Config(create_app(), log_config=None, host="127.0.0.1"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE"),
                )
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{port}")
                    page.get_by_label("Username", exact=True).fill("test-user")
                    page.get_by_label("Password", exact=True).fill("test-password")
                    page.get_by_role("button", name="Create login & open archive").click()
                    page.get_by_role("link", name="Subscriptions", exact=True).click()
                    page.get_by_role("button", name="Add Subscription", exact=False).first.click()
                    dialog = page.get_by_role("dialog", name="Add subscription")
                    dialog.get_by_label("YouTube URL", exact=False).fill(
                        "https://www.youtube.com/@fixture"
                    )
                    dialog.get_by_label("Regular Videos", exact=True).uncheck()
                    dialog.get_by_label("YouTube Shorts", exact=True).check()
                    dialog.get_by_label("Auto-download new videos", exact=True).check()
                    dialog.get_by_role("button", name="Create Subscription", exact=True).click()
                    dialog.wait_for(state="hidden")
                    sub = page.request.get(f"http://127.0.0.1:{port}/api/subscriptions").json()[
                        "subscriptions"
                    ][0]
                    assert sub["content_types"] == ["short"]
                    page.get_by_role("link", name="Downloads", exact=True).click()
                    page.get_by_role(
                        "heading", name=f"Video {support.SECOND_ID}", exact=True
                    ).wait_for()
                    page.get_by_role("link", name="Open local video").wait_for()
                    page.get_by_role("link", name="Videos", exact=True).click()
                    page.get_by_role(
                        "button", name=f"Video {support.SECOND_ID}", exact=False
                    ).click()
                    page.locator("dialog video").wait_for()
                    page.wait_for_function('document.querySelector("dialog video").readyState >= 2')
                    assert page.locator("dialog video").evaluate("(video) => video.duration") > 0
                    page.keyboard.press("Escape")
                    page.get_by_role("dialog").wait_for(state="hidden")
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.get_by_role("link", name="Subscriptions", exact=True).is_visible()
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    )
                    assert not errors, errors
                finally:
                    browser.close()
        finally:
            server.should_exit = True
            source.hold_downloads = False
            thread.join(timeout=10)
            assert not thread.is_alive(), "Server did not shut down"

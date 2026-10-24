"""YouTube test double and integration-test context."""

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.core.database import Database
from app.core.downloader import Downloader

VIDEO_ID = "dQw4w9WgXcQ"
SECOND_ID = "AK47SC6kr_A"
CHANNEL_ID = "UCuAXFkgsw1L7xaCfnd5JJOw"
MEDIA = b"local-video-fixture-" * 100


class FakeYouTube:
    def __init__(self) -> None:
        self.extract_calls: list[tuple[str, dict | None]] = []
        self.download_calls: list[tuple[str, Path, dict]] = []
        self.fail_download = False
        self.fail_source = False
        self.hold_downloads = False
        self.write_media = True
        self.entries = [VIDEO_ID, SECOND_ID]
        self.entries_by_tab: dict[str, list[str]] = {}
        self.metadata: dict[str, dict[str, Any]] = {}

    async def extract_info(self, url: str, extra_config: dict | None = None) -> dict:
        self.extract_calls.append((url, extra_config))
        await asyncio.sleep(0)
        if "/watch?v=" in url:
            return self.video_info(url.split("v=")[1])
        if self.fail_source:
            raise RuntimeError("YouTube source is unavailable")
        tab = url.rsplit("/", 1)[-1]
        entries = self.entries_by_tab.get(tab, self.entries)
        return {
            "id": "PLfixture" if "playlist?" in url else CHANNEL_ID,
            "channel_id": CHANNEL_ID,
            "title": "Fixture source",
            "channel": "Fixture source",
            "entries": [self.video_info(video_id) for video_id in entries],
        }

    def video_info(self, youtube_id: str) -> dict[str, Any]:
        return {
            "id": youtube_id,
            "channel_id": CHANNEL_ID if youtube_id == VIDEO_ID else "UCdifferentUploader123456",
            "channel": "First uploader" if youtube_id == VIDEO_ID else "Second uploader",
            "title": f"Video {youtube_id}",
            "description": "Fixture description",
            "duration": 12.5,
            "upload_date": "20250101",
            "height": 720,
            **self.metadata.get(youtube_id, {}),
        }

    async def download_with_progress(
        self,
        url: str,
        output_path: Path,
        progress_callback=None,
        extra_config: dict | None = None,
    ) -> bool:
        self.download_calls.append((url, output_path, extra_config or {}))
        while self.hold_downloads:
            await asyncio.sleep(0.01)
        if self.fail_download:
            raise RuntimeError("Download failed: expired YouTube login")
        if self.write_media:
            (output_path / "video.mp4").write_bytes(MEDIA)
        (output_path / "thumbnail.jpg").write_bytes(b"fixture-image")
        (output_path / "video.info.json").write_text(
            json.dumps(self.video_info(url.split("v=")[1]))
        )
        if progress_callback:
            progress_callback(
                {"status": "finished", "downloaded_bytes": len(MEDIA), "total_bytes": len(MEDIA)}
            )
        return True

    def get_status(self) -> dict:
        return {"failure_count": 0, "is_backing_off": False, "next_available_in": 0}


@dataclass
class TestEnvironment:
    __test__ = False

    client: TestClient
    fake: FakeYouTube
    root: Path
    db: Database
    downloader: Downloader


def wait_job(env: TestEnvironment, job_id: int | None = None, state: str = "completed") -> dict:
    deadline = time.monotonic() + 5
    jobs = []
    while time.monotonic() < deadline:
        response = env.client.get("/api/downloads")
        assert response.status_code == 200, response.text
        jobs = response.json()["downloads"]
        job = next((job for job in jobs if job_id is None or job["id"] == job_id), None)
        if job and job["status"] == state:
            return job
        time.sleep(0.02)
    raise AssertionError(f"Job did not reach {state}: {jobs}")


def add_video(env: TestEnvironment, youtube_id: str = VIDEO_ID, **options) -> dict:
    response = env.client.post("/api/videos", json={"youtube_id": youtube_id, **options})
    assert response.status_code == 201, response.text
    return response.json()


def subscription(env: TestEnvironment, **options) -> dict:
    response = env.client.post(
        "/api/subscriptions",
        json={
            "source_url": "https://www.youtube.com/playlist?list=PLfixture",
            "subscription_type": "playlist",
            "enabled": False,
            **options,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()

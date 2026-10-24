"""An app per test with a temporary database and media folder and a fake YouTube."""

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import config
from main import create_app
from tests.fake_youtube import FakeYouTube


@dataclass
class Archive:
    client: TestClient
    youtube: FakeYouTube
    media: Path

    @property
    def app(self):
        return self.client.app

    def call(self, function: Callable, *args: Any) -> Any:
        """Run a coroutine function on the app's event loop."""
        return self.client.portal.call(function, *args)

    def sql(self, query: str, params: tuple = ()) -> list[dict]:
        return self.call(self.app.state.db.fetch_all, query, params)

    def job(self, job_id: int) -> dict:
        return next(job for job in self.jobs() if job["id"] == job_id)

    def jobs(self, **params: Any) -> list[dict]:
        response = self.client.get("/api/jobs", params={"limit": 200, **params})
        assert response.status_code == 200, response.text
        return response.json()["items"]

    def wait(self, condition: Callable[[], Any], timeout: float = 5) -> Any:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if result := condition():
                return result
            time.sleep(0.02)
        raise AssertionError("Timed out waiting for condition")

    def wait_job(self, job_id: int, status: str = "completed") -> dict:
        return self.wait(lambda: (job := self.job(job_id))["status"] == status and job)

    def wait_idle(self) -> None:
        def idle() -> bool:
            counts = self.client.get("/api/jobs", params={"limit": 1}).json()["counts"]
            return counts["queued"] + counts["running"] == 0

        self.wait(idle)


@pytest.fixture
def anonymous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Archive]:
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path / "media")
    youtube = FakeYouTube()
    with TestClient(create_app(youtube=youtube)) as client:
        try:
            yield Archive(client, youtube, (tmp_path / "media").resolve())
        finally:
            youtube.hold.clear()


@pytest.fixture
def archive(anonymous: Archive) -> Archive:
    response = anonymous.client.post(
        "/api/auth/setup", json={"username": "owner", "password": "correct horse"}
    )
    assert response.status_code == 200, response.text
    return anonymous

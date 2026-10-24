"""Application fixtures with temporary SQLite and media storage."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.endpoints import subscriptions
from app.core import downloader
from app.core.config import settings
from main import create_app
from tests.support import FakeYouTube, TestEnvironment


@pytest.fixture
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestEnvironment]:
    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "data/archive.db"))
    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(settings, "MAX_CONCURRENT_DOWNLOADS", 2)
    fake = FakeYouTube()
    monkeypatch.setattr(downloader, "get_ytdlp_service", lambda: fake)
    monkeypatch.setattr(subscriptions, "get_ytdlp_service", lambda: fake)
    monkeypatch.setattr(downloader.shutil, "which", lambda name: "/fixture/ffmpeg")
    with TestClient(create_app()) as client:
        try:
            yield TestEnvironment(
                client, fake, tmp_path, client.app.state.db, client.app.state.downloader
            )
        finally:
            fake.hold_downloads = False


@pytest.fixture
def archive(environment: TestEnvironment) -> TestEnvironment:
    response = environment.client.post(
        "/api/auth/setup", json={"username": "test-user", "password": "test-password"}
    )
    assert response.status_code == 200, response.text
    return environment

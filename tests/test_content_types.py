"""Per-subscription content filters through discovery and download queueing."""

import pytest

from tests.support import SECOND_ID, VIDEO_ID, TestEnvironment, subscription, wait_job

REPLAY_ID = "aqz-KE-bpKQ"
LIVE_ID = "jNQXAC9IVRw"


@pytest.mark.parametrize(
    ("content_types", "expected_tabs", "expected_videos"),
    [
        (["video"], {"videos"}, {VIDEO_ID: "video"}),
        (["short"], {"shorts"}, {SECOND_ID: "short"}),
        (["live"], {"streams"}, {REPLAY_ID: "live"}),
        (
            ["video", "short", "live"],
            {"videos", "shorts", "streams"},
            {VIDEO_ID: "video", SECOND_ID: "short", REPLAY_ID: "live"},
        ),
    ],
)
def test_channel_filters_select_tabs_and_persist_types(
    archive: TestEnvironment,
    content_types: list[str],
    expected_tabs: set[str],
    expected_videos: dict[str, str],
) -> None:
    archive.fake.entries_by_tab = {
        "videos": [VIDEO_ID],
        "shorts": [SECOND_ID],
        "streams": [REPLAY_ID, LIVE_ID],
    }
    archive.fake.metadata[LIVE_ID] = {"is_live": True, "live_status": "is_live"}
    sub = subscription(
        archive,
        source_url="https://www.youtube.com/@fixture",
        subscription_type="channel",
        content_types=content_types,
        auto_download=True,
    )
    archive.fake.extract_calls.clear()
    response = archive.client.post(f"/api/subscriptions/{sub['id']}/check")
    assert response.status_code == 202
    job = wait_job(archive, response.json()["job_id"])
    assert not job["result_data"]["errors"]
    assert job["result_data"]["videos_queued"] == len(expected_videos)
    videos = archive.client.get("/api/videos").json()["videos"]
    assert {video["youtube_id"]: video["video_type"] for video in videos} == expected_videos
    tabs = {url.rsplit("/", 1)[-1] for url, _ in archive.fake.extract_calls if "/watch?" not in url}
    assert tabs == expected_tabs
    assert all(
        config["playlistend"] == sub["latest_n_videos"]
        for url, config in archive.fake.extract_calls
        if "/watch?" not in url
    )


def test_filters_are_independent_and_can_be_changed(archive: TestEnvironment) -> None:
    archive.fake.entries_by_tab = {"videos": [VIDEO_ID], "shorts": [SECOND_ID]}
    videos_sub = subscription(
        archive,
        source_url="https://www.youtube.com/@videos-only",
        subscription_type="channel",
        content_types=["video"],
    )
    shorts_sub = subscription(
        archive,
        source_url="https://www.youtube.com/@shorts-only",
        subscription_type="channel",
        content_types=["short"],
    )
    for sub in (videos_sub, shorts_sub):
        response = archive.client.post(f"/api/subscriptions/{sub['id']}/check")
        wait_job(archive, response.json()["job_id"])
    client = archive.client
    assert client.get(f"/api/subscriptions/{videos_sub['id']}").json()["content_types"] == ["video"]
    assert client.get(f"/api/subscriptions/{shorts_sub['id']}").json()["content_types"] == ["short"]
    assert (
        client.put(f"/api/subscriptions/{videos_sub['id']}", json={"content_types": []}).status_code
        == 422
    )
    assert (
        client.put(
            f"/api/subscriptions/{videos_sub['id']}", json={"content_types": ["short"]}
        ).status_code
        == 200
    )
    assert client.get(f"/api/subscriptions/{shorts_sub['id']}").json()["content_types"] == ["short"]
    assert client.get("/api/videos").json()["total"] == 2


def test_playlist_filter_recognizes_replays_and_shorts(archive: TestEnvironment) -> None:
    archive.fake.entries = [VIDEO_ID, SECOND_ID, REPLAY_ID]
    archive.fake.metadata[SECOND_ID] = {
        "webpage_url": f"https://www.youtube.com/shorts/{SECOND_ID}"
    }
    archive.fake.metadata[REPLAY_ID] = {"was_live": True, "live_status": "was_live"}
    sub = subscription(archive, content_types=["short", "live"])
    response = archive.client.post(f"/api/subscriptions/{sub['id']}/check")
    job = wait_job(archive, response.json()["job_id"])
    assert job["result_data"]["videos_filtered"] == 1
    videos = archive.client.get("/api/videos").json()["videos"]
    assert {video["youtube_id"]: video["video_type"] for video in videos} == {
        SECOND_ID: "short",
        REPLAY_ID: "live",
    }

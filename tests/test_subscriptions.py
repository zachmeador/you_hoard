"""Subscriptions keep an inventory; download policies decide what gets archived."""

from tests.fake_youtube import CHANNEL_ID, OTHER_CHANNEL_ID, PLAYLIST_ID

CHANNEL_URL = "https://www.youtube.com/@fixture"
PLAYLIST_URL = f"https://www.youtube.com/playlist?list={PLAYLIST_ID}"


def ids(prefix: str, count: int) -> list[str]:
    return [f"{prefix}{index:0>{11 - len(prefix)}}" for index in range(count)]


def subscribe(archive, url=CHANNEL_URL, **fields):
    response = archive.client.post("/api/subscriptions", json={"url": url, **fields})
    assert response.status_code == 201, response.text
    sub = response.json()
    archive.wait_idle()
    return archive.client.get(f"/api/subscriptions/{sub['id']}").json()


def check(archive, sub, full=False):
    response = archive.client.post(f"/api/subscriptions/{sub['id']}/check", json={"full": full})
    assert response.status_code == 202
    archive.wait_job(response.json()["job_id"])
    archive.wait_idle()
    return archive.client.get(f"/api/subscriptions/{sub['id']}").json()


def library(archive, **params):
    response = archive.client.get("/api/videos", params={"per_page": 200, **params})
    return {video["youtube_id"]: video for video in response.json()["items"]}


def seed_tab(archive, tab: str, youtube_ids: list[str]) -> None:
    for youtube_id in youtube_ids:
        archive.youtube.add(youtube_id)
    archive.youtube.tabs[tab] = youtube_ids


def test_new_policy_inventories_everything_but_only_archives_later_uploads(archive):
    old = ids("old", 30)
    seed_tab(archive, "video", old)
    sub = subscribe(archive)
    assert sub["kind"] == "channel" and sub["channel"]["youtube_id"] == CHANNEL_ID
    assert sub["url"] == f"https://www.youtube.com/channel/{CHANNEL_ID}"
    assert sub["counts"]["entries"] == 30 and sub["counts"]["not_selected"] == 30
    assert sub["last_check"]["result"] == {
        "listed": 30,
        "new_entries": 0,
        "removed": 0,
        "queued": 0,
        "full": True,
    }
    assert library(archive) == {}

    fresh = ids("new", 2)
    seed_tab(archive, "video", fresh + old)
    sub = check(archive, sub)
    result = sub["last_check"]["result"]
    assert result["full"] is False and result["new_entries"] == 2 and result["queued"] == 2
    assert result["listed"] < 32  # stopped after reaching known uploads
    assert set(library(archive)) == set(fresh)
    assert sub["counts"]["archived"] == 2


def test_recent_and_all_policies_select_from_the_first_listing(archive):
    seed_tab(archive, "video", ids("vid", 5))
    seed_tab(archive, "short", ids("sho", 4))
    sub = subscribe(
        archive, content_types=["video", "short"], download_policy="recent", recent_count=2
    )
    videos = library(archive)
    assert set(videos) == {*ids("vid", 2), *ids("sho", 2)}
    assert {videos[i]["video_type"] for i in ids("sho", 2)} == {"short"}
    tabs = {call[2] for call in archive.youtube.calls if call[0] == "list"}
    assert tabs == {"video", "short"}

    updated = archive.client.patch(
        f"/api/subscriptions/{sub['id']}", json={"download_policy": "all"}
    )
    assert updated.status_code == 200
    archive.wait_idle()
    assert len(library(archive)) == 9


def test_checks_never_requeue_removed_or_failed_videos(archive):
    seed_tab(archive, "video", ids("vid", 2))
    archive.youtube.download_failures[ids("vid", 2)[1]] = RuntimeError("ffmpeg exploded")
    sub = subscribe(archive, download_policy="all")
    videos = library(archive)
    archived, failed = ids("vid", 2)
    assert videos[archived]["status"] == "archived" and videos[failed]["status"] == "failed"
    assert archive.client.delete(f"/api/videos/{videos[archived]['id']}").status_code == 200
    downloads = sum(1 for call in archive.youtube.calls if call[0] == "download")
    check(archive, sub, full=True)
    assert sum(1 for call in archive.youtube.calls if call[0] == "download") == downloads


def test_playlists_take_every_entry_and_resolve_uploaders_on_download(archive):
    first, second = ids("pla", 2)
    archive.youtube.add(first)
    archive.youtube.add(second, channel_id=OTHER_CHANNEL_ID, channel="Someone Else")
    archive.youtube.playlist = [first, second]
    sub = subscribe(archive, PLAYLIST_URL, download_policy="all")
    assert sub["kind"] == "playlist" and sub["owner_name"] == "Playlist Owner"
    assert sub["channel"] is None
    videos = library(archive)
    assert {videos[first]["channel"]["youtube_id"], videos[second]["channel"]["youtube_id"]} == {
        CHANNEL_ID,
        OTHER_CHANNEL_ID,
    }
    channels = archive.client.get("/api/channels").json()["items"]
    assert {channel["name"] for channel in channels} == {"Fixture Channel", "Someone Else"}


def test_full_rescan_marks_entries_gone_from_the_source(archive):
    seed_tab(archive, "video", ids("vid", 3))
    sub = subscribe(archive)
    archive.youtube.tabs["video"] = ids("vid", 3)[1:]
    sub = check(archive, sub, full=True)
    assert sub["counts"]["removed"] == 1
    entries = archive.client.get(f"/api/subscriptions/{sub['id']}/entries").json()["items"]
    assert [entry["removed_at"] is not None for entry in entries] == [False, False, True]


def test_inventory_entries_can_be_downloaded_one_at_a_time(archive):
    seed_tab(archive, "video", ids("vid", 3))
    sub = subscribe(archive)
    url = f"/api/subscriptions/{sub['id']}/entries"
    entries = archive.client.get(url, params={"status": "not_selected"}).json()
    assert entries["total"] == 3
    target = entries["items"][2]["youtube_id"]
    queued = archive.client.post(f"{url}/{target}/download")
    assert queued.status_code == 200
    archive.wait_job(queued.json()["job_id"])
    archived = archive.client.get(url, params={"status": "archived"}).json()["items"]
    assert [entry["youtube_id"] for entry in archived] == [target]
    assert archive.client.post(f"{url}/{target}/download").status_code == 409


def test_adding_a_tab_lists_it_and_removing_a_subscription_keeps_videos(archive):
    seed_tab(archive, "video", ids("vid", 1))
    seed_tab(archive, "live", ids("liv", 1))
    sub = subscribe(archive, download_policy="all")
    assert set(library(archive)) == set(ids("vid", 1))
    patched = archive.client.patch(
        f"/api/subscriptions/{sub['id']}", json={"content_types": ["video", "live"]}
    )
    assert patched.status_code == 200
    archive.wait_idle()
    assert library(archive)[ids("liv", 1)[0]]["video_type"] == "live"
    assert archive.client.delete(f"/api/subscriptions/{sub['id']}").status_code == 200
    assert len(library(archive)) == 2
    assert archive.client.get("/api/subscriptions").json()["items"] == []


def test_resolve_create_and_validation(archive):
    client = archive.client
    resolved = client.post("/api/subscriptions/resolve", json={"url": CHANNEL_URL + "/videos"})
    assert resolved.json()["existing_subscription_id"] is None
    sub = subscribe(archive, enabled=False)
    assert sub["next_check_at"] is None and sub["last_check"] is None
    again = client.post("/api/subscriptions/resolve", json={"url": CHANNEL_URL}).json()
    assert again["existing_subscription_id"] == sub["id"]
    assert client.post("/api/subscriptions", json={"url": CHANNEL_URL}).status_code == 409
    assert (
        client.post("/api/subscriptions/resolve", json={"url": "https://youtu.be/x"}).status_code
        == 422
    )
    bad = client.patch(f"/api/subscriptions/{sub['id']}", json={"content_types": []})
    assert bad.status_code == 422
    assert (
        client.patch(f"/api/subscriptions/{sub['id']}", json={"enabled": None}).status_code == 422
    )
    defaults = client.patch(f"/api/subscriptions/{sub['id']}", json={"quality": "720p"}).json()
    assert defaults["quality"] == "720p"
    cleared = client.patch(f"/api/subscriptions/{sub['id']}", json={"quality": None}).json()
    assert cleared["quality"] is None


def test_scheduler_queues_due_checks_and_reschedules(archive):
    seed_tab(archive, "video", ids("vid", 1))
    sub = subscribe(archive, check_interval_hours=24)
    archive.sql("UPDATE subscriptions SET next_check_at = '2000-01-01T00:00:00Z'")
    assert archive.call(archive.app.state.runner.queue_due_checks) == 1
    archive.wait_idle()
    current = archive.client.get(f"/api/subscriptions/{sub['id']}").json()
    assert current["next_check_at"] > "2001"
    assert archive.call(archive.app.state.runner.queue_due_checks) == 0


def test_streams_that_air_after_subscribing_count_as_new(archive):
    stream = ids("liv", 1)[0]
    archive.youtube.add(stream, live_status="is_upcoming")
    archive.youtube.tabs["live"] = [stream]
    sub = subscribe(archive, content_types=["live"])
    assert library(archive) == {}
    archive.youtube.videos[stream].live_status = "was_live"
    check(archive, sub)
    assert library(archive)[stream]["status"] == "archived"

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


def test_inventory_entries_carry_their_pending_download(archive):
    running, paused, waiting = ids("pend", 3)
    seed_tab(archive, "video", [running, paused, waiting])
    sub = subscribe(archive)
    url = f"/api/subscriptions/{sub['id']}/entries"
    archive.youtube.hold.set()
    archive.client.put("/api/settings", json={"max_concurrent_downloads": 1})
    jobs = {
        youtube_id: archive.client.post(f"{url}/{youtube_id}/download").json()["job_id"]
        for youtube_id in (running, paused, waiting)
    }
    archive.wait_job(jobs[running], "running")
    archive.client.post("/api/jobs/pause", json={"ids": [jobs[paused]]})
    later = "2099-01-01T00:00:00Z"
    archive.sql("UPDATE jobs SET run_after = ? WHERE id = ?", (later, jobs[waiting]))

    entries = {entry["youtube_id"]: entry for entry in archive.client.get(url).json()["items"]}
    assert entries[running]["job"]["status"] == "running"
    held = {"status": "paused", "run_after": None, "attempts": 0, "error": None}
    assert entries[paused]["status"] == "queued" and entries[paused]["job"] == held
    assert entries[waiting]["job"]["status"] == "queued"
    assert entries[waiting]["job"]["run_after"] == later


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
    assert resolved.json()["channel_handle"] == "@fixture"
    assert resolved.json()["subscriber_count"] == 1234
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


def test_inventory_entries_carry_views_and_the_uploader(archive):
    first, second = ids("pla", 2)
    archive.youtube.add(first, view_count=1500)
    archive.youtube.add(second, channel_id=OTHER_CHANNEL_ID, channel="Someone Else", view_count=77)
    archive.youtube.playlist = [first, second]
    sub = subscribe(archive, PLAYLIST_URL)
    url = f"/api/subscriptions/{sub['id']}/entries"

    def inventory():
        items = archive.client.get(url).json()["items"]
        return [(e["youtube_id"], e["channel_name"], e["view_count"]) for e in items]

    assert inventory() == [(first, "Fixture Channel", 1500), (second, "Someone Else", 77)]
    archive.youtube.videos[second].view_count = 90
    check(archive, sub)
    assert inventory() == [(first, "Fixture Channel", 1500), (second, "Someone Else", 90)]


def test_channel_inventories_show_views_under_the_channels_own_name(archive):
    seed_tab(archive, "video", ids("vid", 2))
    archive.youtube.videos[ids("vid", 2)[0]].view_count = 4200
    sub = subscribe(archive)
    entries = archive.client.get(f"/api/subscriptions/{sub['id']}/entries").json()["items"]
    assert [(e["channel_name"], e["view_count"]) for e in entries] == [
        ("Fixture Channel", 4200),
        ("Fixture Channel", 1000),
    ]


def test_queued_playlist_videos_show_their_channel_before_they_download(archive):
    first = ids("pla", 1)[0]
    archive.youtube.add(first, channel_id=OTHER_CHANNEL_ID, channel="Someone Else")
    archive.youtube.playlist = [first]
    sub = subscribe(archive, PLAYLIST_URL)
    runner = archive.app.state.runner
    archive.call(runner.stop)
    queued = archive.client.post(f"/api/subscriptions/{sub['id']}/entries/{first}/download").json()
    video = archive.client.get(f"/api/videos/{queued['video_id']}").json()
    assert video["status"] == "queued"
    assert video["channel"]["name"] == "Someone Else"
    assert video["channel"]["youtube_id"] == OTHER_CHANNEL_ID
    archive.call(runner.start)
    archive.wait_job(queued["job_id"])


def test_playlist_downloads_queued_by_policy_also_know_their_channel(archive):
    first = ids("pla", 1)[0]
    archive.youtube.add(first, channel_id=OTHER_CHANNEL_ID, channel="Someone Else")
    archive.youtube.playlist = [first]
    archive.youtube.hold.set()
    response = archive.client.post(
        "/api/subscriptions", json={"url": PLAYLIST_URL, "download_policy": "all"}
    )
    assert response.status_code == 201
    videos = archive.wait(lambda: archive.client.get("/api/videos").json()["items"])
    assert videos[0]["status"] in ("queued", "downloading")
    assert videos[0]["channel"]["name"] == "Someone Else"
    archive.youtube.hold.clear()
    archive.wait_idle()

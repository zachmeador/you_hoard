"""Status counts for the library tabs, the unavailable filter, view sorting and the waiting queue."""

from tests.fake_youtube import OTHER_CHANNEL_ID
from tests.test_library import add

IDS = {
    "alpha": "lib00000001",
    "bravo": "lib00000002",
    "charlie": "lib00000003",
    "delta": "lib00000004",
    "echo": "lib00000005",
    "foxtrot": "lib00000006",
    "golf": "lib00000007",
    "hotel": "lib00000008",
}


def build_library(archive):
    """Alpha, Bravo and Charlie archived (Bravo gone from YouTube, Charlie from another channel,
    Alpha watched), Delta failed and gone, Echo waiting for a premiere, Foxtrot removed, Golf known
    only by ID and Hotel downloading."""
    youtube = archive.youtube
    youtube.add(IDS["alpha"], "Alpha", view_count=500)
    youtube.add(IDS["bravo"], "Bravo", view_count=9000)
    youtube.add(IDS["charlie"], "Charlie", view_count=70, channel_id=OTHER_CHANNEL_ID, channel="B")
    youtube.add(IDS["delta"], "Delta")
    youtube.add(IDS["echo"], "Echo", live_status="is_upcoming")
    youtube.add(IDS["foxtrot"], "Foxtrot")
    youtube.add(IDS["hotel"], "Hotel", channel_id=OTHER_CHANNEL_ID, channel="B")
    youtube.download_failures[IDS["delta"]] = RuntimeError("ffmpeg exploded")

    videos = {}
    for name in ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot"):
        videos[name] = add(archive, IDS[name])
        job_id = videos[name]["job_id"]
        if name == "echo":
            archive.wait(lambda job_id=job_id: archive.job(job_id)["run_after"])
        else:
            archive.wait_job(job_id, "failed" if name == "delta" else "completed")
    archive.client.delete(f"/api/videos/{videos['foxtrot']['id']}")
    archive.client.post(f"/api/videos/{videos['alpha']['id']}/watched", json={"watched": True})
    archive.sql(
        "UPDATE videos SET unavailable_at = '2026-09-18T00:00:00Z' WHERE youtube_id IN (?, ?, ?)",
        (IDS["bravo"], IDS["delta"], IDS["foxtrot"]),
    )
    archive.sql(
        "INSERT INTO videos (youtube_id, title, channel_id) VALUES (?, 'Golf', 1)", (IDS["golf"],)
    )
    youtube.hold.set()
    videos["hotel"] = add(archive, IDS["hotel"])
    archive.wait_job(videos["hotel"]["job_id"], "running")
    return videos


def counts(archive, **params):
    response = archive.client.get("/api/videos/counts", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def titles(archive, **params):
    response = archive.client.get("/api/videos", params={"per_page": 200, **params})
    return [video["title"] for video in response.json()["items"]]


def test_counts_give_every_status_tab_its_number(archive):
    build_library(archive)
    assert counts(archive) == {
        "all": 7,
        "archived": 3,
        "downloading": 1,
        "queued": 1,
        "failed": 1,
        "missing": 1,
        "deleted": 1,
        "unavailable": 2,
    }
    # The numbers agree with what each tab lists.
    for status in ("archived", "downloading", "queued", "failed", "missing", "deleted"):
        total = archive.client.get("/api/videos", params={"status": status}).json()["total"]
        assert total == counts(archive)[status], status
    assert archive.client.get("/api/videos").json()["total"] == counts(archive)["all"]


def test_counts_follow_the_list_filters_except_status(archive):
    build_library(archive)

    def only(**params):
        return {key: value for key, value in counts(archive, **params).items() if value}

    channel = archive.sql("SELECT id FROM channels WHERE name = 'B'")[0]["id"]
    assert only(channel_id=channel) == {"all": 2, "archived": 1, "downloading": 1}
    assert only(watched=True) == {"all": 1, "archived": 1}
    assert only(q="alp") == {"all": 1, "archived": 1}
    assert only(video_type="short") == {}
    assert only(unavailable=True) == {
        "all": 2,
        "archived": 1,
        "failed": 1,
        "deleted": 1,
        "unavailable": 2,
    }
    assert only(unavailable=False) == {
        "all": 5,
        "archived": 2,
        "downloading": 1,
        "queued": 1,
        "missing": 1,
    }
    assert archive.client.get("/api/videos/counts", params={"watched": "maybe"}).status_code == 422


def test_gone_from_youtube_is_a_filter_on_any_tab(archive):
    build_library(archive)
    assert sorted(titles(archive, unavailable=True)) == ["Bravo", "Delta"]
    assert titles(archive, unavailable=True, status="failed") == ["Delta"]
    assert titles(archive, unavailable=True, status="deleted") == ["Foxtrot"]
    assert sorted(titles(archive, unavailable=False, status="archived")) == ["Alpha", "Charlie"]
    gone = archive.client.get("/api/videos", params={"unavailable": True}).json()["items"]
    assert all(video["unavailable"] and video["unavailable_at"] for video in gone)


def test_videos_sort_by_views(archive):
    build_library(archive)
    assert titles(archive, status="archived", sort="views") == ["Bravo", "Alpha", "Charlie"]
    ascending = titles(archive, status="archived", sort="views", order="asc")
    assert ascending == ["Charlie", "Alpha", "Bravo"]
    assert archive.client.get("/api/videos", params={"sort": "likes"}).status_code == 422


def test_jobs_wait_for_a_premiere_without_counting_as_queued(archive):
    build_library(archive)
    counts = archive.client.get("/api/jobs").json()["counts"]
    assert counts["waiting"] == 1 and counts["queued"] == 0
    assert counts["running"] == 1 and counts["failed"] == 1

    waiting = archive.client.get("/api/jobs", params={"status": "queued"}).json()
    assert [job["video"]["title"] for job in waiting["items"]] == ["Echo"]
    assert waiting["items"][0]["run_after"] > "2026"

    queue = archive.client.get("/api/system").json()["queue"]
    assert queue == {"queued": 0, "waiting": 1, "running": 1, "failed": 1}

    archive.sql("UPDATE jobs SET run_after = NULL WHERE status = 'queued'")
    now = archive.client.get("/api/jobs").json()["counts"]
    assert now["waiting"] == 0 and now["queued"] == 1

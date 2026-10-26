"""Status counts for the library tabs, the unavailable filter, view sorting and the waiting queue."""

from tests.fake_youtube import OTHER_CHANNEL_ID
from tests.test_library import OTHER, VIDEO, add

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

    waiting = archive.client.get("/api/jobs", params={"status": "waiting"}).json()
    assert [job["video"]["title"] for job in waiting["items"]] == ["Echo"]
    assert waiting["items"][0]["run_after"] > "2026"
    assert archive.client.get("/api/jobs", params={"status": "queued"}).json()["total"] == 0

    queue = archive.client.get("/api/system").json()["queue"]
    assert queue == {"queued": 0, "waiting": 1, "running": 1, "failed": 1}

    archive.sql("UPDATE jobs SET run_after = NULL WHERE status = 'queued'")
    now = archive.client.get("/api/jobs", params={"status": "queued"}).json()
    assert [job["video"]["title"] for job in now["items"]] == ["Echo"]
    assert now["counts"]["waiting"] == 0 and now["counts"]["queued"] == 1


def test_videos_carry_their_download_job_until_it_finishes(archive):
    videos = build_library(archive)

    def job(name):
        return archive.client.get(f"/api/videos/{videos[name]['id']}").json()["job"]

    assert job("alpha") is None and job("delta") is None and job("foxtrot") is None
    assert job("hotel")["status"] == "running"
    echo = job("echo")
    assert echo["status"] == "queued" and echo["run_after"] > "2026"

    archive.client.post("/api/jobs/pause", json={"ids": [videos["echo"]["job_id"]]})
    listed = archive.client.get("/api/videos", params={"per_page": 200}).json()["items"]
    paused = next(video for video in listed if video["title"] == "Echo")
    assert paused["status"] == "queued" and paused["job"]["status"] == "paused"
    assert paused["job"]["run_after"] == echo["run_after"]


def job_list(archive, **params):
    response = archive.client.get("/api/jobs", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_waiting_jobs_list_apart_from_queued_ones_soonest_first(archive):
    archive.client.put("/api/settings", json={"max_concurrent_downloads": 1})
    waiting = []
    for youtube_id in ("wait0000001", "wait0000002", "wait0000003"):
        archive.youtube.add(youtube_id, live_status="is_upcoming")
        waiting.append(add(archive, youtube_id)["job_id"])
    for job_id in waiting:
        archive.wait(lambda job_id=job_id: archive.job(job_id)["run_after"])
    first, second, third = waiting
    for job_id, day in ((first, 2), (second, 1), (third, 2)):
        run_after = f"2099-01-0{day}T00:00:00Z"
        archive.sql("UPDATE jobs SET run_after = ? WHERE id = ?", (run_after, job_id))

    archive.youtube.hold.set()
    for youtube_id in (VIDEO, OTHER):
        archive.youtube.add(youtube_id)
    running, ready = (add(archive, youtube_id)["job_id"] for youtube_id in (VIDEO, OTHER))
    archive.wait_job(running, "running")

    listed = job_list(archive, status="waiting")
    assert [job["id"] for job in listed["items"]] == [second, first, third]
    assert [job["id"] for job in job_list(archive, status="queued")["items"]] == [ready]
    page = job_list(archive, status="waiting", limit=1, offset=1)
    assert [job["id"] for job in page["items"]] == [first] and page["total"] == 3
    for status in ("queued", "waiting", "running"):
        assert job_list(archive, status=status)["total"] == listed["counts"][status]


def test_jobs_take_several_statuses_and_their_counts_follow_the_kind(archive):
    for name in ("alpha", "bravo", "charlie"):
        archive.youtube.add(IDS[name])
    for name in ("alpha", "bravo"):
        archive.wait_job(add(archive, IDS[name])["job_id"])
    archive.youtube.hold.set()
    held = add(archive, IDS["charlie"])["job_id"]
    archive.wait_job(held, "running")
    archive.client.post(f"/api/jobs/{held}/cancel")
    archive.wait_job(held, "cancelled")
    archive.wait_job(archive.client.post("/api/library/rescan").json()["job_id"])

    def only(counts):
        return {status: n for status, n in counts.items() if n}

    both = ["completed", "cancelled"]
    everything = job_list(archive, status=both)
    assert everything["total"] == 4 and {job["status"] for job in everything["items"]} == set(both)
    last = job_list(archive, status=both, limit=3, offset=3)
    assert last["total"] == 4 and len(last["items"]) == 1
    scans = job_list(archive, status=both, kind="scan")
    assert scans["total"] == 1 and [job["kind"] for job in scans["items"]] == ["scan"]
    assert job_list(archive, status="cancelled")["total"] == 1

    assert only(job_list(archive)["counts"]) == {"completed": 3, "cancelled": 1}
    assert only(job_list(archive, kind="scan")["counts"]) == {"completed": 1}
    downloads = job_list(archive, kind="download", status="cancelled")
    assert only(downloads["counts"]) == {"completed": 2, "cancelled": 1}
    assert archive.client.get("/api/jobs", params={"status": "nope"}).status_code == 422

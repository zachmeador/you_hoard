"""Library rescans rebuild the index from files, including TubeArchivist's layout."""

import argparse
import json

from app.__main__ import rescan as command_line_rescan
from tests.fake_youtube import CHANNEL_ID, MEDIA
from tests.test_library import VIDEO, add


def rescan(archive) -> dict:
    response = archive.client.post("/api/library/rescan")
    assert response.status_code == 202
    return archive.wait_job(response.json()["job_id"])["result"]


def test_rescan_adds_files_with_and_without_sidecars(archive):
    ours = archive.media / f"Someone [{CHANNEL_ID}]"
    ours.mkdir(parents=True)
    (ours / "2020-02-02 A Title [AK47SC6kr_A].mkv").write_bytes(MEDIA)
    (ours / "2020-02-02 A Title [AK47SC6kr_A].info.json").write_text(
        json.dumps(
            {
                "id": "AK47SC6kr_A",
                "title": "A Title",
                "channel_id": CHANNEL_ID,
                "channel": "Someone",
                "upload_date": "20200202",
                "height": 720,
                "width": 1280,
            }
        )
    )
    tubearchivist = archive.media / "UCtubearchivistLayout123"
    tubearchivist.mkdir()
    (tubearchivist / "jNQXAC9IVRw.mp4").write_bytes(MEDIA)
    legacy = archive.media / "Old Channel Name"
    legacy.mkdir()
    (legacy / "20190308_M7lc1UVf-VE_Old naming.mp4").write_bytes(MEDIA)
    (archive.media / ".youhoard" / "incomplete" / "aqz-KE-bpKQ").mkdir(parents=True)
    (archive.media / ".youhoard" / "incomplete" / "aqz-KE-bpKQ" / "media.mp4").write_bytes(MEDIA)

    assert rescan(archive) == {"files": 3, "added": 3, "relinked": 0, "missing": 0, "duplicates": 0}
    videos = {v["youtube_id"]: v for v in archive.client.get("/api/videos").json()["items"]}
    assert videos["AK47SC6kr_A"]["title"] == "A Title"
    assert videos["AK47SC6kr_A"]["published_at"] == "2020-02-02"
    assert videos["AK47SC6kr_A"]["quality"] == "720p"
    assert videos["jNQXAC9IVRw"]["channel"]["youtube_id"] == "UCtubearchivistLayout123"
    assert videos["M7lc1UVf-VE"]["title"] == "Old naming"
    assert all(video["status"] == "archived" for video in videos.values())
    assert rescan(archive)["added"] == 0


def test_rescan_relinks_moved_files_and_flags_missing_ones(archive):
    archive.youtube.add(VIDEO)
    archive.youtube.add("AK47SC6kr_A")
    first = add(archive, VIDEO)
    second = add(archive, "AK47SC6kr_A")
    archive.wait_idle()
    moved = archive.client.get(f"/api/videos/{first['id']}").json()["media_path"]
    gone = archive.client.get(f"/api/videos/{second['id']}").json()["media_path"]
    target = archive.media / "elsewhere" / f"{VIDEO}.mp4"
    target.parent.mkdir()
    (archive.media / moved).rename(target)
    (archive.media / gone).unlink()

    result = rescan(archive)
    assert result["relinked"] == 1 and result["missing"] == 1
    assert (
        archive.client.get(f"/api/videos/{first['id']}").json()["media_path"]
        == f"elsewhere/{VIDEO}.mp4"
    )
    assert archive.client.get(f"/api/videos/{second['id']}").json()["status"] == "missing"


def lose_most_of_the_library(archive, count: int = 12) -> None:
    """Videos the database says are archived, with no files, as when the media folder is unmounted."""
    for number in range(count):
        archive.sql(
            "INSERT INTO videos (youtube_id, title, media_path) VALUES (?, 'Gone', ?)",
            (f"lost{number:07d}", f"Channel/lost{number:07d}.mp4"),
        )


def test_a_rescan_that_would_empty_the_library_declines_and_says_so(archive):
    lose_most_of_the_library(archive)
    queued = archive.client.post("/api/library/rescan").json()
    failed = archive.wait_job(queued["job_id"], "failed")
    assert failed["reason"] == "declined" and failed["error"].startswith("Rescan stopped:")
    assert (
        archive.sql("SELECT count(*) AS n FROM videos WHERE media_path IS NOT NULL")[0]["n"] == 12
    )
    declined = next(e for e in archive.events(job_id=failed["id"]) if e["event"] == "job.failed")
    assert (declined["actor"], declined["reason"]) == ("app", "declined")

    forced = archive.client.post("/api/library/rescan", json={"force": True}).json()
    result = archive.wait_job(forced["job_id"])["result"]
    assert result["missing"] == 12


def test_the_command_line_stops_a_rescan_that_would_empty_the_library(archive, capsys):
    lose_most_of_the_library(archive)
    db = archive.app.state.db
    assert archive.call(command_line_rescan, argparse.Namespace(force=False), db) == 1
    assert "Rescan stopped" in capsys.readouterr().err
    assert not [e for e in archive.events() if e["event"] == "scan.completed"]

    assert archive.call(command_line_rescan, argparse.Namespace(force=True), db) == 0
    assert "missing: 12" in capsys.readouterr().out
    scan = next(e for e in archive.events() if e["event"] == "scan.completed")
    assert scan["actor"] == "cli" and scan["detail"].endswith("12 missing")


def test_a_video_whose_file_is_lost_says_when_until_it_is_found_or_fetched_again(archive):
    archive.youtube.add(VIDEO)
    video = add(archive)
    archive.wait_job(video["job_id"])

    def lost_at():
        return archive.client.get(f"/api/videos/{video['id']}").json()["lost_at"]

    path = archive.media / archive.client.get(f"/api/videos/{video['id']}").json()["media_path"]
    assert lost_at() is None
    path.rename(path.with_name("away.mp4.hidden"))
    rescan(archive)
    assert lost_at() > "2026"
    assert archive.client.get(f"/api/videos/{video['id']}").json()["status"] == "missing"

    # Found again, in another place: the rescan picks it up and forgets it was lost.
    elsewhere = archive.media / "elsewhere" / f"{VIDEO}.mp4"
    elsewhere.parent.mkdir()
    path.with_name("away.mp4.hidden").rename(elsewhere)
    assert rescan(archive)["added"] == 1
    assert lost_at() is None

    # Lost once more, then downloaded again.
    elsewhere.unlink()
    rescan(archive)
    assert lost_at() > "2026"
    again = archive.client.post(f"/api/videos/{video['id']}/download", json={}).json()
    archive.wait_job(again["job_id"])
    assert lost_at() is None
    assert archive.client.get(f"/api/videos/{video['id']}").json()["status"] == "archived"

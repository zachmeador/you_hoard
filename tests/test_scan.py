"""Library rescans rebuild the index from files, including TubeArchivist's layout."""

import json

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
    tubearchivist = archive.media / "UCtubearchivistLayout1234"
    tubearchivist.mkdir()
    (tubearchivist / "jNQXAC9IVRw.mp4").write_bytes(MEDIA)
    (archive.media / ".youhoard" / "incomplete" / "aqz-KE-bpKQ").mkdir(parents=True)
    (archive.media / ".youhoard" / "incomplete" / "aqz-KE-bpKQ" / "media.mp4").write_bytes(MEDIA)

    assert rescan(archive) == {"files": 2, "added": 2, "relinked": 0, "missing": 0, "duplicates": 0}
    videos = {v["youtube_id"]: v for v in archive.client.get("/api/videos").json()["items"]}
    assert videos["AK47SC6kr_A"]["title"] == "A Title"
    assert videos["AK47SC6kr_A"]["published_at"] == "2020-02-02"
    assert videos["AK47SC6kr_A"]["quality"] == "720p"
    assert videos["jNQXAC9IVRw"]["channel"]["youtube_id"] == "UCtubearchivistLayout1234"
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

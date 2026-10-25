"""Removed files wait in the trash so a removal can be undone, and rescans can't wipe the library."""

import glob
import json

from app import trash
from tests.test_library import VIDEO, add


def archived(archive) -> dict:
    archive.youtube.add(VIDEO)
    video = add(archive)
    archive.wait_job(video["job_id"])
    return archive.client.get(f"/api/videos/{video['id']}").json()


def remove(archive, video: dict) -> dict:
    response = archive.client.delete(f"/api/videos/{video['id']}")
    assert response.status_code == 200, response.text
    return response.json()


def test_removing_moves_files_to_the_trash_and_restore_puts_them_back(archive):
    video = archived(archive)
    media = archive.media / video["media_path"]
    names = sorted(path.name for path in media.parent.glob(glob.escape(media.stem) + ".*"))
    assert len(names) > 1  # the media and its sidecars

    assert remove(archive, video)["trash"]
    assert not media.exists()
    [entry] = trash.entries()
    assert sorted(entry.files) == names and entry.youtube_id == VIDEO
    removed = archive.client.get(f"/api/videos/{video['id']}").json()
    assert removed["status"] == "deleted"
    assert removed["trash"]["expires_at"] > removed["trash"]["removed_at"]

    assert archive.client.post(f"/api/videos/{video['id']}/restore").status_code == 200
    restored = archive.client.get(f"/api/videos/{video['id']}").json()
    assert restored["status"] == "archived" and restored["trash"] is None
    for key in ("media_path", "width", "height", "archived_at", "subtitles"):
        assert restored[key] == video[key], key
    assert archive.client.get(restored["media_url"]).status_code == 200
    assert trash.entries() == []


def test_with_the_trash_off_files_are_deleted_for_good(archive):
    assert archive.client.put("/api/settings", json={"trash_days": 0}).status_code == 200
    video = archived(archive)
    assert remove(archive, video)["trash"] is None
    assert trash.entries() == []
    assert not (archive.media / video["media_path"]).exists()
    assert archive.client.post(f"/api/videos/{video['id']}/restore").status_code == 404


def test_restore_never_overwrites(archive):
    video = archived(archive)
    media = archive.media / video["media_path"]
    remove(archive, video)
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"someone else's")

    assert archive.client.post(f"/api/videos/{video['id']}/restore").status_code == 409
    assert media.read_bytes() == b"someone else's"
    assert len(trash.entries()) == 1  # still restorable once the way is clear


def test_expiry_deletes_only_expired_entries_and_the_files_they_list(archive):
    video = archived(archive)
    remove(archive, video)
    [entry] = trash.entries()
    (entry.path / "not-ours.txt").write_text("keep")
    unknown = trash.trash_dir() / "something else"
    unknown.mkdir()
    (unknown / f"x [{VIDEO}].mp4").write_text("keep")

    assert trash.purge() == 0
    manifest = json.loads((entry.path / trash.MANIFEST).read_text())
    manifest["expires_at"] = "2000-01-01T00:00:00Z"
    (entry.path / trash.MANIFEST).write_text(json.dumps(manifest))
    assert trash.purge() == 1

    assert [path.name for path in entry.path.iterdir()] == ["not-ours.txt"]
    assert (unknown / f"x [{VIDEO}].mp4").read_text() == "keep"
    assert archive.client.get(f"/api/videos/{video['id']}").json()["trash"] is None


def test_a_rescan_never_takes_files_out_of_the_trash(archive):
    video = archived(archive)
    remove(archive, video)
    job = archive.client.post("/api/library/rescan").json()
    archive.wait_job(job["job_id"])
    assert archive.client.get(f"/api/videos/{video['id']}").json()["status"] == "deleted"


def test_a_rescan_refuses_to_mark_most_of_the_library_missing(archive):
    for n in range(12):
        youtube_id = f"gone{n:07d}"
        archive.sql(
            "INSERT INTO videos (youtube_id, title, media_path, media_size, archived_at) "
            "VALUES (?, ?, ?, 1, '2026-01-01T00:00:00Z')",
            (youtube_id, youtube_id, f"Gone [UCxxxxxxxxxxxxxxxxxxxxxx]/x [{youtube_id}].mp4"),
        )
    still_archived = "SELECT count(*) AS n FROM videos WHERE media_path IS NOT NULL"

    job = archive.client.post("/api/library/rescan").json()
    refused = archive.wait_job(job["job_id"], "failed")
    assert refused["error"].startswith("Rescan stopped: 12 of 12 archived videos")
    assert archive.sql(still_archived)[0]["n"] == 12

    job = archive.client.post("/api/library/rescan", json={"force": True}).json()
    forced = archive.wait_job(job["job_id"])
    assert forced["result"]["missing"] == 12
    assert archive.sql(still_archived)[0]["n"] == 0

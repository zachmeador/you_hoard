"""Download options resolve per video, then per subscription, then library settings."""

import pytest

from tests.test_library import OTHER, VIDEO, add
from tests.test_subscriptions import CHANNEL_URL, ids, seed_tab, subscribe

LIBRARY = {
    "default_quality": "480p",
    "subtitle_languages": ["de"],
    "auto_captions": False,
    "download_comments": True,
    "audio_languages": ["es"],
    "live_chat": True,
    "sponsorblock": True,
}


def requested(archive):
    """The options the adapter was last asked to download with."""
    request = archive.youtube.calls[-1][1]
    return {
        "quality": request.quality,
        "subtitle_languages": request.subtitle_languages,
        "auto_captions": request.auto_captions,
        "download_comments": request.comments,
        "audio_languages": request.audio_languages,
        "live_chat": request.live_chat,
        "sponsorblock": request.sponsorblock,
    }


def library_options(**changes):
    options = {
        "quality": "480p",
        "subtitle_languages": ["de"],
        "auto_captions": False,
        "download_comments": True,
        "audio_languages": ["es"],
        "live_chat": True,
        "sponsorblock": True,
    }
    return {**options, **changes}


def test_new_libraries_start_with_conservative_defaults(archive):
    settings = archive.client.get("/api/settings").json()
    assert settings["audio_languages"] == [] and settings["auto_captions"] is True
    assert settings["live_chat"] is False and settings["sponsorblock"] is False
    languages = settings["options"]["languages"]
    assert 35 <= len(languages) <= 50
    assert {"code": "en", "name": "English"} in languages
    assert all(set(language) == {"code", "name"} for language in languages)

    archive.youtube.add(VIDEO)
    archive.wait_job(add(archive)["job_id"])
    assert requested(archive) == {
        "quality": "1080p",
        "subtitle_languages": ["en"],
        "auto_captions": True,
        "download_comments": False,
        "audio_languages": [],
        "live_chat": False,
        "sponsorblock": False,
    }


def test_library_settings_round_trip(archive):
    updated = archive.client.put(
        "/api/settings", json={**LIBRARY, "audio_languages": [" es ", "", "de"]}
    ).json()
    assert updated["audio_languages"] == ["es", "de"]
    assert updated["live_chat"] is True and updated["sponsorblock"] is True
    assert updated["auto_captions"] is False
    cleared = archive.client.put("/api/settings", json={"audio_languages": []}).json()
    assert cleared["audio_languages"] == []
    assert cleared["sponsorblock"] is True


def test_a_video_added_by_hand_follows_the_library(archive):
    archive.client.put("/api/settings", json=LIBRARY)
    archive.youtube.add(VIDEO)
    archive.wait_job(add(archive)["job_id"])
    assert requested(archive) == library_options()


def test_a_video_overrides_the_library(archive):
    archive.client.put("/api/settings", json=LIBRARY)
    archive.youtube.add(VIDEO)
    own = {
        "quality": "360p",
        "subtitle_languages": [],
        "auto_captions": True,
        "download_comments": False,
        "audio_languages": [],
        "live_chat": False,
        "sponsorblock": False,
    }
    archive.wait_job(add(archive, **own)["job_id"])
    assert requested(archive) == own

    archive.youtube.add(OTHER)
    partial = archive.client.post(
        "/api/videos", json={"url": OTHER, "download_comments": False, "audio_languages": ["fr"]}
    )
    archive.wait_job(partial.json()["job_id"])
    assert requested(archive) == library_options(download_comments=False, audio_languages=["fr"])


def test_downloading_a_removed_video_again_takes_new_options(archive):
    archive.youtube.add(VIDEO)
    video = add(archive)
    archive.wait_job(video["job_id"])
    archive.client.delete(f"/api/videos/{video['id']}")
    response = archive.client.post(
        f"/api/videos/{video['id']}/download", json={"quality": "360p", "sponsorblock": True}
    )
    archive.wait_job(response.json()["job_id"])
    assert requested(archive)["quality"] == "360p" and requested(archive)["sponsorblock"] is True


def test_a_subscription_overrides_the_library_and_a_video_overrides_both(archive):
    archive.client.put("/api/settings", json=LIBRARY)
    seed_tab(archive, "video", ids("vid", 3))
    sub = subscribe(
        archive,
        download_policy="none",
        quality="720p",
        audio_languages=["fr"],
        sponsorblock=False,
        live_chat=False,
        subtitle_languages=["en", "es"],
    )
    assert sub["quality"] == "720p" and sub["audio_languages"] == ["fr"]
    assert sub["sponsorblock"] is False and sub["live_chat"] is False
    assert sub["auto_captions"] is None and sub["download_comments"] is None

    first, second, third = ids("vid", 3)
    url = f"/api/subscriptions/{sub['id']}/entries"
    archive.wait_job(archive.client.post(f"{url}/{first}/download").json()["job_id"])
    assert requested(archive) == library_options(
        quality="720p",
        audio_languages=["fr"],
        sponsorblock=False,
        live_chat=False,
        subtitle_languages=["en", "es"],
    )

    runner = archive.app.state.runner
    archive.call(runner.stop)
    queued = archive.client.post(f"{url}/{second}/download").json()
    video_id = queued["video_id"]
    again = archive.client.post(
        f"/api/videos/{video_id}/download", json={"quality": "360p", "audio_languages": []}
    )
    assert again.json()["job_id"] == queued["job_id"]
    archive.call(runner.start)
    archive.wait_job(queued["job_id"])
    assert requested(archive) == library_options(
        quality="360p",
        audio_languages=[],
        sponsorblock=False,
        live_chat=False,
        subtitle_languages=["en", "es"],
    )

    cleared = archive.client.patch(
        f"/api/subscriptions/{sub['id']}", json={"quality": None, "audio_languages": None}
    ).json()
    assert cleared["quality"] is None and cleared["audio_languages"] is None
    archive.wait_job(archive.client.post(f"{url}/{third}/download").json()["job_id"])
    assert requested(archive) == library_options(
        sponsorblock=False, live_chat=False, subtitle_languages=["en", "es"]
    )


def test_overrides_can_be_set_and_updated_on_a_subscription(archive):
    seed_tab(archive, "video", ids("vid", 1))
    sub = subscribe(archive, download_policy="none")
    for key in ("audio_languages", "auto_captions", "live_chat", "sponsorblock"):
        assert sub[key] is None, key
    patched = archive.client.patch(
        f"/api/subscriptions/{sub['id']}",
        json={
            "audio_languages": [" de ", "es"],
            "auto_captions": False,
            "live_chat": True,
            "sponsorblock": True,
        },
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["audio_languages"] == ["de", "es"] and body["auto_captions"] is False
    assert body["live_chat"] is True and body["sponsorblock"] is True
    listed = archive.client.get("/api/subscriptions").json()["items"][0]
    assert listed["audio_languages"] == ["de", "es"]
    nothing = archive.client.patch(f"/api/subscriptions/{sub['id']}", json={"audio_languages": []})
    assert nothing.json()["audio_languages"] == []


@pytest.mark.parametrize(
    "body",
    [{"quality": "9999p"}, {"audio_languages": "es"}, {"sponsorblock": "sometimes"}],
)
def test_bad_options_are_rejected(archive, body):
    archive.youtube.add(VIDEO)
    assert archive.client.post("/api/videos", json={"url": VIDEO, **body}).status_code == 422
    video = add(archive)
    archive.wait_job(video["job_id"])
    archive.client.delete(f"/api/videos/{video['id']}")
    assert archive.client.post(f"/api/videos/{video['id']}/download", json=body).status_code == 422
    assert (
        archive.client.post("/api/subscriptions", json={"url": CHANNEL_URL, **body}).status_code
        == 422
    )

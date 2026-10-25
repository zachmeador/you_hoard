"""Channel details: verification, avatars and banners kept as files, and ordering."""

from tests.fake_youtube import (
    AVATAR,
    AVATAR_SIZED_URL,
    AVATAR_URL,
    BANNER,
    BANNER_URL,
    CHANNEL_ID,
)
from tests.test_library import add
from tests.test_scan import rescan
from tests.test_subscriptions import check, ids, seed_tab, subscribe


def folder(archive):
    return archive.media / f"Fixture Channel [{CHANNEL_ID}]"


def fetched(archive):
    return [call[1] for call in archive.youtube.calls if call[0] == "image"]


def channel_of(archive, sub):
    response = archive.client.get(f"/api/channels/{sub['channel']['id']}")
    assert response.status_code == 200
    return response.json()


def test_subscribing_saves_the_avatar_and_banner_in_the_channel_folder(archive):
    seed_tab(archive, "video", ids("vid", 2))
    sub = subscribe(archive, download_policy="none")

    assert (folder(archive) / "channel.jpg").read_bytes() == AVATAR
    assert (folder(archive) / "banner.jpg").read_bytes() == BANNER
    channel = channel_of(archive, sub)
    assert channel["avatar_url"] == f"/api/channels/{channel['id']}/avatar"
    assert channel["banner_url"] == f"/api/channels/{channel['id']}/banner"
    assert sub["channel"]["avatar_url"] == channel["avatar_url"]
    assert channel["verified"] is True and channel["subscriber_count"] == 1234

    avatar = archive.client.get(channel["avatar_url"])
    assert avatar.status_code == 200 and avatar.content == AVATAR
    assert avatar.headers["content-type"] == "image/jpeg"
    assert archive.client.get(channel["banner_url"]).content == BANNER
    assert archive.client.get("/api/channels").json()["items"][0]["avatar_url"]

    # The creation fetched them and the first check found them in place.
    assert fetched(archive) == [AVATAR_URL, BANNER_URL]
    check(archive, sub, full=True)
    assert fetched(archive) == [AVATAR_URL, BANNER_URL]


def test_a_failed_download_leaves_the_check_alone_and_the_next_check_retries(archive):
    seed_tab(archive, "video", ids("vid", 2))
    working = dict(archive.youtube.images)
    archive.youtube.images.clear()
    sub = subscribe(archive, download_policy="none")
    assert sub["last_check"]["status"] == "completed"
    assert sub["last_check"]["result"]["listed"] == 2
    assert sub["channel"]["avatar_url"] is None
    assert channel_of(archive, sub)["banner_url"] is None
    assert not (folder(archive) / "channel.jpg").exists()
    avatar = archive.client.get(f"/api/channels/{sub['channel']['id']}/avatar")
    assert avatar.status_code == 404

    archive.youtube.images.update(working)
    sub = check(archive, sub)
    assert sub["channel"]["avatar_url"]
    assert (folder(archive) / "channel.jpg").read_bytes() == AVATAR


def test_the_sized_avatar_stands_in_for_an_uncropped_one_that_fails(archive):
    archive.youtube.images = {AVATAR_SIZED_URL: AVATAR, BANNER_URL: BANNER}
    seed_tab(archive, "video", ids("vid", 1))
    sub = subscribe(archive, download_policy="none")
    assert (folder(archive) / "channel.jpg").read_bytes() == AVATAR
    assert fetched(archive)[:2] == [AVATAR_URL, AVATAR_SIZED_URL]
    assert channel_of(archive, sub)["avatar_url"]


def test_art_that_is_not_a_jpeg_is_not_kept(archive):
    archive.youtube.images[AVATAR_URL] = b"<html>an error page</html>"
    seed_tab(archive, "video", ids("vid", 1))
    sub = subscribe(archive, download_policy="none")
    assert not (folder(archive) / "channel.jpg").exists()
    assert channel_of(archive, sub)["avatar_url"] is None
    assert channel_of(archive, sub)["banner_url"]


def test_art_already_in_the_folder_is_never_replaced(archive):
    folder(archive).mkdir(parents=True)
    (folder(archive) / "channel.jpg").write_bytes(b"\xff\xd8\xffmy own avatar")
    seed_tab(archive, "video", ids("vid", 1))
    sub = subscribe(archive, download_policy="none")
    assert (folder(archive) / "channel.jpg").read_bytes() == b"\xff\xd8\xffmy own avatar"
    assert AVATAR_URL not in fetched(archive)
    assert channel_of(archive, sub)["avatar_url"]


def test_a_folder_that_cannot_be_written_never_fails_the_check(archive):
    folder(archive).write_text("in the way")
    seed_tab(archive, "video", ids("vid", 2))
    sub = subscribe(archive, download_policy="none")
    assert sub["last_check"]["status"] == "completed"
    assert sub["last_check"]["result"]["listed"] == 2
    assert channel_of(archive, sub)["avatar_url"] is None


def test_a_rescan_links_art_and_forgets_art_that_is_gone(archive):
    seed_tab(archive, "video", ids("vid", 1))
    sub = subscribe(archive, download_policy="none")
    archive.sql("UPDATE channels SET avatar_path = NULL, banner_path = NULL")
    assert channel_of(archive, sub)["avatar_url"] is None
    rescan(archive)
    assert channel_of(archive, sub)["avatar_url"] and channel_of(archive, sub)["banner_url"]

    (folder(archive) / "banner.jpg").unlink()
    rescan(archive)
    channel = channel_of(archive, sub)
    assert channel["avatar_url"] and channel["banner_url"] is None


def test_checks_keep_the_verified_badge_current(archive):
    seed_tab(archive, "video", ids("vid", 1))
    sub = subscribe(archive, download_policy="none")
    assert channel_of(archive, sub)["verified"] is True
    archive.youtube.verified = False
    check(archive, sub)
    assert channel_of(archive, sub)["verified"] is False


def test_channels_sort_by_name_size_or_videos(archive):
    names = {"UCalpha0000000000000000": "alpha", "UCbeta00000000000000000": "Beta"}
    names["UCgamma000000000000000"] = "Gamma"
    sizes = {"alpha": [9000], "Beta": [100, 100, 100], "Gamma": [500, 500]}
    count = 0
    for channel_id, name in names.items():
        for size in sizes[name]:
            youtube_id = f"chn{count:0>8}"
            count += 1
            archive.youtube.add(youtube_id, channel_id=channel_id, channel=name)
            video = add(archive, youtube_id)
            archive.wait_job(video["job_id"])
            archive.sql("UPDATE videos SET media_size = ? WHERE id = ?", (size, video["id"]))

    def order(**params):
        items = archive.client.get("/api/channels", params=params).json()["items"]
        return [channel["name"] for channel in items]

    assert order() == ["alpha", "Beta", "Gamma"]
    assert order(sort="name") == ["alpha", "Beta", "Gamma"]
    assert order(sort="size") == ["alpha", "Gamma", "Beta"]
    assert order(sort="videos") == ["Beta", "Gamma", "alpha"]
    assert archive.client.get("/api/channels", params={"sort": "newest"}).status_code == 422


def test_channels_met_through_videos_have_no_art_or_badge(archive):
    archive.youtube.add("vid00000001")
    video = add(archive, "vid00000001")
    archive.wait_job(video["job_id"])
    channel = archive.client.get("/api/channels").json()["items"][0]
    assert channel["avatar_url"] is None and channel["banner_url"] is None
    assert channel["verified"] is False

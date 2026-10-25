"""Extra audio languages, SponsorBlock segments, comments and live chat replay."""

import pytest

from tests.fake_youtube import chat_line
from tests.test_details import archived, sidecar_of
from tests.test_library import VIDEO

DUBBED = {"en-US": 10, "es": -1, "de": -1, "fr-FR": -1, "en-US-desc": -10}


def test_extra_audio_languages_that_exist_follow_the_original(archive):
    archive.youtube.add(VIDEO, audio=DUBBED)
    video = archived(archive, audio_languages=["fr", "ja", "de"])
    assert video["audio_languages"] == ["en-US", "fr-FR", "de"]
    assert archive.youtube.calls[-1][1].audio_languages == ["fr", "ja", "de"]
    assert sidecar_of(archive, video)["_youhoard"]["audio_languages"] == ["en-US", "fr-FR", "de"]


@pytest.mark.parametrize("wanted", [["en"], ["en-US"], ["EN"]])
def test_the_original_language_is_never_added_twice(archive, wanted):
    archive.youtube.add(VIDEO, audio=DUBBED)
    assert archived(archive, audio_languages=wanted)["audio_languages"] == ["en-US"]


def test_descriptive_tracks_are_not_dubs(archive):
    archive.youtube.add(VIDEO, audio={"en-US": 10, "es": -1, "en-US-desc": -10})
    video = archived(archive, audio_languages=["en-US-desc", "es"])
    assert video["audio_languages"] == ["en-US", "es"]


def test_a_single_track_video_has_no_extras_to_add(archive):
    archive.youtube.add(VIDEO, audio={"en": -1})
    assert archived(archive, audio_languages=["es"])["audio_languages"] == ["en"]


def test_extra_audio_defaults_to_nothing(archive):
    archive.youtube.add(VIDEO, audio=DUBBED)
    video = archived(archive)
    assert video["audio_languages"] == ["en-US"]
    assert archive.youtube.calls[-1][1].audio_languages == []


def test_sponsorblock_segments_are_kept_as_markers(archive):
    archive.youtube.add(
        VIDEO,
        sponsor_segments=[(60.0, 75.5, "sponsor"), (5.0, 12.0, "intro"), (80.0, 81.0, "chapter")],
    )
    video = archived(archive, sponsorblock=True)
    assert video["sponsor_segments"] == [
        {"start": 5.0, "end": 12.0, "category": "intro"},
        {"start": 60.0, "end": 75.5, "category": "sponsor"},
    ]
    assert len(sidecar_of(archive, video)["sponsorblock_chapters"]) == 3
    assert archive.youtube.calls[-1][1].sponsorblock is True


def test_sponsorblock_is_off_by_default(archive):
    archive.youtube.add(VIDEO, sponsor_segments=[(60.0, 75.5, "sponsor")])
    video = archived(archive)
    assert video["sponsor_segments"] == []
    assert "sponsorblock_chapters" not in sidecar_of(archive, video)


def test_a_failed_sponsorblock_lookup_does_not_fail_the_video(archive):
    archive.youtube.add(VIDEO, sponsor_segments=None)
    video = archived(archive, sponsorblock=True)
    assert video["status"] == "archived" and video["sponsor_segments"] == []


COMMENTS = [
    {"id": "a", "parent": "root", "text": "Quiet", "like_count": 2, "timestamp": 1000},
    {"id": "b", "parent": "root", "text": "Popular", "like_count": 50, "timestamp": 2000},
    {"id": "a.1", "parent": "a", "text": "Later reply", "timestamp": 1600},
    {"id": "a.2", "parent": "a", "text": "Earlier reply", "timestamp": 1200},
    {
        "id": "c",
        "parent": "root",
        "text": "Pinned by the creator",
        "like_count": 1,
        "timestamp": 500,
        "is_pinned": True,
        "author": "Creator",
        "author_id": "UC1",
        "author_is_uploader": True,
        "author_is_verified": True,
        "is_favorited": True,
    },
    {"id": "d", "parent": "root", "text": "Newest", "like_count": 0, "timestamp": 3000},
    {"id": "lost.1", "parent": "missing", "text": "Reply to a lost comment", "timestamp": 10},
]


def comments_of(archive, video, **params):
    response = archive.client.get(f"/api/videos/{video['id']}/comments", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_comments_are_threads_with_pinned_first_then_likes(archive):
    archive.youtube.add(VIDEO, comment_count=900, comments=COMMENTS)
    video = archived(archive, download_comments=True)
    assert video["comments"] == {
        "saved": len(COMMENTS),
        "url": f"/api/videos/{video['id']}/comments",
    }
    assert video["comment_count"] == 900  # YouTube's count, not the number saved

    page = comments_of(archive, video)
    assert [c["id"] for c in page["items"]] == ["c", "b", "a", "d", "lost.1"]
    assert page["total"] == 5
    pinned = page["items"][0]
    assert pinned == {
        "id": "c",
        "text": "Pinned by the creator",
        "author": "Creator",
        "author_id": "UC1",
        "author_is_uploader": True,
        "author_is_verified": True,
        "is_pinned": True,
        "is_favorited": True,
        "like_count": 1,
        "timestamp": 500,
        "replies": [],
    }
    quiet = next(c for c in page["items"] if c["id"] == "a")
    assert [r["id"] for r in quiet["replies"]] == ["a.2", "a.1"]
    assert "replies" not in quiet["replies"][0]


def test_comments_can_be_sorted_newest_first_and_paged(archive):
    archive.youtube.add(VIDEO, comments=COMMENTS)
    video = archived(archive, download_comments=True)
    newest = comments_of(archive, video, sort="new")
    assert [c["id"] for c in newest["items"]] == ["d", "b", "a", "c", "lost.1"]

    first = comments_of(archive, video, sort="new", per_page=2)
    second = comments_of(archive, video, sort="new", per_page=2, page=2)
    third = comments_of(archive, video, sort="new", per_page=2, page=3)
    assert [c["id"] for c in first["items"]] == ["d", "b"]
    assert [c["id"] for c in second["items"]] == ["a", "c"]
    assert [c["id"] for c in third["items"]] == ["lost.1"]
    assert first["total"] == second["total"] == third["total"] == 5


def test_damaged_comment_data_still_pages(archive):
    archive.youtube.add(
        VIDEO,
        comments=[
            {"id": "x", "parent": "y", "text": "A loop", "timestamp": 3},
            {"id": "y", "parent": "x", "text": "The other half", "timestamp": 4},
            {"id": "self", "parent": "self", "text": "Its own parent"},
            {"id": "top", "parent": "root", "text": "Fine", "like_count": "many"},
            {"id": "deep", "parent": "top.1", "text": "A reply to a reply", "timestamp": 9},
            {"id": "top.1", "parent": "top", "text": "Reply", "timestamp": 8},
            {"text": "No id at all"},
            "not even a comment",
        ],
    )
    video = archived(archive, download_comments=True)
    page = comments_of(archive, video)
    assert sorted(c["id"] for c in page["items"]) == ["self", "top", "x", "y"]
    top = next(c for c in page["items"] if c["id"] == "top")
    assert top["like_count"] == 0
    assert [r["id"] for r in top["replies"]] == ["top.1", "deep"]


def test_videos_without_saved_comments_have_none(archive):
    archive.youtube.add(VIDEO)
    video = archived(archive)
    assert video["comments"] is None
    assert comments_of(archive, video) == {"items": [], "total": 0, "page": 1, "per_page": 20}
    assert archive.client.get("/api/videos/999/comments").status_code == 404


def test_comments_need_a_valid_sort(archive):
    archive.youtube.add(VIDEO)
    video = archived(archive)
    response = archive.client.get(f"/api/videos/{video['id']}/comments", params={"sort": "oldest"})
    assert response.status_code == 422


def test_live_chat_replay_is_parsed_into_messages(archive):
    archive.youtube.add(
        VIDEO,
        live_status="was_live",
        chat=[
            chat_line(2500, "Ada", "hello everyone"),
            "not json at all",
            chat_line(-4000, "Early", "before the start"),
            chat_line(61000, "Grace", "thanks!", amount="$5.00"),
            chat_line(61000, "Linus", ""),
        ],
    )
    video = archived(archive, live_chat=True)
    assert video["chat_url"] == f"/api/videos/{video['id']}/chat"
    assert any(f["kind"] == "chat" for f in video["files"])

    response = archive.client.get(video["chat_url"])
    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {"t": 0.0, "author": "Early", "text": "before the start"},
            {"t": 2.5, "author": "Ada", "text": "hello everyone"},
            {"t": 61.0, "author": "Grace", "text": "$5.00 thanks!"},
        ]
    }

    window = archive.client.get(video["chat_url"], params={"since": 2.5, "until": 61}).json()
    assert [message["author"] for message in window["items"]] == ["Ada"]
    later = archive.client.get(video["chat_url"], params={"since": 3}).json()
    assert [message["author"] for message in later["items"]] == ["Grace"]
    assert archive.client.get(video["chat_url"], params={"since": -1}).status_code == 422


def test_chat_is_only_kept_when_asked_for_and_available(archive):
    archive.youtube.add(VIDEO, chat=[chat_line(1000, "Ada", "hi")])
    video = archived(archive)
    assert video["chat_url"] is None
    assert archive.client.get(f"/api/videos/{video['id']}/chat").status_code == 404

    archive.youtube.add("AK47SC6kr_A")  # no replay on YouTube
    other = archived(archive, "AK47SC6kr_A", live_chat=True)
    assert other["chat_url"] is None

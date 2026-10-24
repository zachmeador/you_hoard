"""Accept YouTube sources, not arbitrary server-side fetch URLs."""

import re
from urllib.parse import parse_qs, urlparse

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")


def youtube_url(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if (
        parsed.scheme not in ("http", "https")
        or parsed.hostname
        not in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be")
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 80, 443)
    ):
        raise ValueError("Use a YouTube URL")
    return value


def subscription_url(value: str, subscription_type: str) -> str:
    parsed = urlparse(youtube_url(value))
    if subscription_type == "playlist":
        playlist_id = parse_qs(parsed.query).get("list", [""])[0]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", playlist_id):
            raise ValueError("Use a YouTube playlist URL with a list ID")
        return f"https://www.youtube.com/playlist?list={playlist_id}"
    path = parsed.path.rstrip("/")
    for tab in ("/videos", "/shorts", "/streams", "/featured"):
        path = path.removesuffix(tab)
    if not re.fullmatch(r"/(?:@[^/]+|(?:channel|c|user)/[^/]+)", path):
        raise ValueError("Use a YouTube channel URL, such as https://www.youtube.com/@channel")
    return f"https://www.youtube.com{path}"


def video_id_from_url(value: str) -> str:
    parsed = urlparse(youtube_url(value))
    if parsed.hostname == "youtu.be":
        video_id = parsed.path.strip("/")
    elif parsed.path == "/watch":
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    elif re.match(r"^/(shorts|live|embed)/", parsed.path):
        video_id = parsed.path.split("/")[2]
    else:
        video_id = ""
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError("Use a video URL, not a channel or playlist URL")
    return video_id

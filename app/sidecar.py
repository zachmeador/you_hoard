"""What an archived video's files hold besides the video: chapters, comments, chat and file lists."""

import bisect
import functools
import json
from pathlib import Path
from typing import Any

from app import layout

SUBTITLE_EXTENSIONS = {
    ".vtt",
    ".srt",
    ".ass",
    ".ssa",
    ".ttml",
    ".lrc",
    ".json3",
    ".srv1",
    ".srv2",
    ".srv3",
}
CHAT_MESSAGES = ("liveChatTextMessageRenderer", "liveChatPaidMessageRenderer")


def number(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return value
    return None


def read_info(media: Path) -> dict[str, Any]:
    path = layout.info_for(media)
    if path is None:
        return {}
    try:
        info = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return info if isinstance(info, dict) else {}


def spans(items: Any, value_key: str | None = None) -> list[dict[str, Any]]:
    """yt-dlp's start_time/end_time entries as {start, end} in seconds, plus one other field."""
    result = []
    for item in items or ():
        if not isinstance(item, dict):
            continue
        start, end = number(item.get("start_time")), number(item.get("end_time"))
        if start is None or end is None:
            continue
        span = {"start": start, "end": end}
        if value_key:
            span[value_key] = item.get(value_key)
        result.append(span)
    return result


def chapters(info: dict[str, Any]) -> list[dict[str, Any]]:
    return [{**span, "title": span["title"] or ""} for span in spans(info.get("chapters"), "title")]


def heatmap(info: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        span for span in spans(info.get("heatmap"), "value") if number(span["value"]) is not None
    ]


def sponsor_segments(info: dict[str, Any]) -> list[dict[str, Any]]:
    segments = [
        span
        for span in spans(info.get("sponsorblock_chapters"), "category")
        if span["category"] and span["category"] != "chapter" and span["end"] > span["start"]
    ]
    return sorted(segments, key=lambda segment: segment["start"])


def comment_out(raw: dict[str, Any]) -> dict[str, Any]:
    likes, timestamp = number(raw.get("like_count")), number(raw.get("timestamp"))
    return {
        "id": str(raw["id"]),
        "text": raw.get("text") or "",
        "author": raw.get("author"),
        "author_id": raw.get("author_id"),
        "author_is_uploader": bool(raw.get("author_is_uploader")),
        "author_is_verified": bool(raw.get("author_is_verified")),
        "is_pinned": bool(raw.get("is_pinned")),
        "is_favorited": bool(raw.get("is_favorited")),
        "like_count": int(likes) if likes is not None and likes > 0 else 0,
        "timestamp": timestamp,
    }


def comment_threads(comments: list[Any], sort: str) -> list[dict[str, Any]]:
    """Top-level comments in the order asked for, each with its replies oldest first. A reply whose
    parent is not among the saved comments counts as top-level."""
    valid = [c for c in comments if isinstance(c, dict) and c.get("id")]
    known = {str(c["id"]) for c in valid}
    parent_of = {
        str(c["id"]): str(c["parent"]) for c in valid if c.get("parent") not in (None, "root")
    }

    def top_level(comment_id: str) -> str:
        seen = {comment_id}
        while (parent := parent_of.get(comment_id)) in known and parent not in seen:
            seen.add(parent)
            comment_id = parent
        return comment_id

    roots = {str(c["id"]): top_level(str(c["id"])) for c in valid}
    tops = {comment_id for comment_id, root in roots.items() if root == comment_id}
    threads: dict[str, dict[str, Any]] = {}
    replies: list[tuple[str, dict[str, Any]]] = []
    for raw in valid:
        comment_id = str(raw["id"])
        comment = comment_out(raw)
        if comment_id in tops or roots[comment_id] not in tops:
            threads[comment_id] = {**comment, "replies": []}
        else:
            replies.append((roots[comment_id], comment))
    for root, reply in replies:
        threads[root]["replies"].append(reply)
    for thread in threads.values():
        thread["replies"].sort(key=lambda reply: reply["timestamp"] or 0)
    ordered = list(threads.values())
    if sort == "new":
        ordered.sort(key=lambda comment: comment["timestamp"] or 0, reverse=True)
    else:
        ordered.sort(key=lambda comment: (not comment["is_pinned"], -comment["like_count"]))
    return ordered


def _chat_text(renderer: dict[str, Any]) -> str:
    parts = []
    for run in (renderer.get("message") or {}).get("runs") or ():
        emoji = run.get("emoji")
        if emoji is None:
            parts.append(run.get("text") or "")
        elif emoji.get("isCustomEmoji"):
            parts.append((emoji.get("shortcuts") or [""])[0])
        else:
            parts.append(emoji.get("emojiId") or "")
    text = "".join(parts)
    amount = (renderer.get("purchaseAmountText") or {}).get("simpleText")
    return f"{amount} {text}".strip() if amount else text


def chat_messages(path: Path) -> list[dict[str, Any]]:
    """Messages from yt-dlp's live chat file: one JSON object per line, `t` in seconds."""
    messages = []
    with path.open(encoding="utf-8", errors="replace") as lines:
        for line in lines:
            try:
                action = json.loads(line)
            except ValueError:
                continue
            if not isinstance(action, dict):
                continue
            replay = action.get("replayChatItemAction") or {}
            offset = replay.get("videoOffsetTimeMsec", action.get("videoOffsetTimeMsec"))
            try:
                seconds = max(int(offset), 0) / 1000
            except (TypeError, ValueError):
                continue
            for entry in replay.get("actions") or ():
                item = (entry.get("addChatItemAction") or {}).get("item") or {}
                for name in CHAT_MESSAGES:
                    renderer = item.get(name)
                    text = _chat_text(renderer) if renderer else ""
                    if text:
                        author = (renderer.get("authorName") or {}).get("simpleText")
                        messages.append({"t": seconds, "author": author or "", "text": text})
    messages.sort(key=lambda message: message["t"])
    return messages


@functools.lru_cache(maxsize=3)
def _parsed_chat(path: str, modified: int, size: int) -> tuple[list[dict[str, Any]], list[float]]:
    messages = chat_messages(Path(path))
    return messages, [message["t"] for message in messages]


def chat_window(path: Path, since: float | None, until: float | None) -> list[dict[str, Any]]:
    """The chat messages from `since` (inclusive) to `until` (exclusive) seconds, or all of them.
    A long replay is parsed once and kept while it is being read."""
    stat = path.stat()
    messages, times = _parsed_chat(str(path), stat.st_mtime_ns, stat.st_size)
    start = 0 if since is None else bisect.bisect_left(times, since)
    end = len(messages) if until is None else bisect.bisect_left(times, until)
    return messages[start:end]


def file_kind(path: Path, media: Path) -> str:
    name = path.name.lower()
    if path == media:
        return "media"
    if name.endswith(".info.json"):
        return "info"
    if name.endswith(".live_chat.json"):
        return "chat"
    if path.suffix in layout.THUMBNAIL_EXTENSIONS:
        return "thumbnail"
    if path.suffix in SUBTITLE_EXTENSIONS:
        return "subtitles"
    return "other"


def files(media: Path) -> list[dict[str, Any]]:
    """The media file and its sidecars, with paths relative to the media folder."""
    result = []
    for path in [media, *layout.sidecars(media)]:
        try:
            size, relative = path.stat().st_size, layout.relative(path)
        except (OSError, ValueError):
            continue
        result.append({"path": relative, "kind": file_kind(path, media), "size": size})
    return result

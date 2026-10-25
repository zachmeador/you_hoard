"""Choosing audio and subtitle tracks from a yt-dlp info dict, and describing the file that results."""

import re
from dataclasses import asdict, dataclass
from typing import Any

from app.languages import language_name

UPLOADED, AUTO, TRANSLATED = "uploaded", "auto", "translated"
LIVE_CHAT = "live_chat"
LANGUAGE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
# The codec families yt-dlp merges into MP4.
MP4_VIDEO = {"avc1", "av01", "hevc"}
MP4_AUDIO = {"mp4a", "ec-3", "ac-4"}
CODEC_FAMILIES = {
    "avc1": "avc1",
    "avc3": "avc1",
    "h264": "avc1",
    "vp9": "vp9",
    "vp09": "vp9",
    "av01": "av01",
    "av1": "av01",
    "hev1": "hevc",
    "hvc1": "hevc",
    "h265": "hevc",
    "hevc": "hevc",
}


@dataclass(frozen=True)
class Track:
    lang: str
    name: str
    source: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def codec_family(codec: str | None) -> str | None:
    if not codec or codec == "none":
        return None
    head = codec.split(".")[0].lower()
    return CODEC_FAMILIES.get(head, head)


def fits_mp4(formats: list[dict[str, Any]]) -> bool:
    for fmt in formats:
        video, audio = codec_family(fmt.get("vcodec")), codec_family(fmt.get("acodec"))
        if (video and video not in MP4_VIDEO) or (audio and audio not in MP4_AUDIO):
            return False
    return True


def audio_tracks(raw: dict[str, Any]) -> dict[str, float]:
    """Languages of the audio-only formats mapped to their preference; the original ranks highest."""
    tracks: dict[str, float] = {}
    for fmt in raw.get("formats") or ():
        language = fmt.get("language")
        if (
            fmt.get("vcodec") != "none"
            or fmt.get("acodec") in (None, "none")
            or not isinstance(language, str)
            or not LANGUAGE.fullmatch(language)
            or language.endswith("-desc")
        ):
            continue
        preference = fmt.get("language_preference") or 0
        tracks[language] = max(tracks.get(language, preference), preference)
    return tracks


def original_language(tracks: dict[str, float]) -> str | None:
    """The track yt-dlp picks first, unless nothing marks one of several as the original."""
    if not tracks:
        return None
    best = max(tracks, key=tracks.__getitem__)
    return best if tracks[best] > 0 or len(tracks) == 1 else None


def covers(code: str, language: str) -> bool:
    """Whether a requested code asks for this track: "en" covers "en" and "en-US"."""
    code, language = code.lower(), language.lower()
    return language == code or language.startswith(code + "-")


def extra_audio(raw: dict[str, Any], wanted: list[str]) -> list[str]:
    """Track languages to add to the original: those wanted that exist, never the original's."""
    tracks = audio_tracks(raw)
    original = original_language(tracks)
    if original is None:
        return []
    chosen: list[str] = []
    for code in wanted:
        if covers(code, original):
            continue
        candidates = [lang for lang in tracks if covers(code, lang) and lang not in chosen]
        exact = [lang for lang in candidates if lang.lower() == code.lower()]
        if candidates:
            chosen.append((exact or candidates)[0])
    return chosen


def file_audio_languages(info: dict[str, Any]) -> list[str]:
    """Languages of the audio tracks in a downloaded file, in file order (the default first)."""
    languages: list[str] = []
    for fmt in info.get("requested_formats") or [info]:
        language = fmt.get("language")
        if fmt.get("acodec") in (None, "none") or not isinstance(language, str) or "+" in language:
            continue
        if language not in languages:
            languages.append(language)
    return languages


def file_codecs(info: dict[str, Any]) -> tuple[str | None, str | None]:
    """Video and audio codec families of a downloaded file."""
    formats = info.get("requested_formats") or [info]
    video = next((fmt for fmt in formats if fmt.get("vcodec") not in (None, "none")), {})
    audio = next((fmt for fmt in formats if fmt.get("acodec") not in (None, "none")), {})
    return codec_family(video.get("vcodec")), codec_family(audio.get("acodec"))


def _matching(pattern: str, uploaded: dict[str, Any], automatic: dict[str, Any]) -> list[str]:
    if pattern.lower() == "all":
        return [key for key in uploaded if key != LIVE_CHAT]
    try:
        matcher = re.compile(pattern, re.IGNORECASE)
    except re.error:
        matcher = re.compile(re.escape(pattern), re.IGNORECASE)
    return [key for key in (*uploaded, *automatic) if key != LIVE_CHAT and matcher.fullmatch(key)]


def _name(entries: Any, lang: str) -> str:
    for entry in entries or ():
        if isinstance(entry, dict) and entry.get("name"):
            return str(entry["name"])
    return language_name(lang) or lang


def plan_subtitles(raw: dict[str, Any], wanted: list[str], auto_captions: bool) -> list[Track]:
    """The subtitle tracks to fetch: uploaded ones first, then automatic and translated captions
    for languages with no uploaded track, so a rate limit costs the least valuable tracks.
    Patterns match whole language codes, so "en" does not pull in "en-GB" or "en-orig"; "all"
    means every uploaded track."""
    uploaded = raw.get("subtitles") or {}
    automatic = (raw.get("automatic_captions") or {}) if auto_captions else {}
    languages = dict.fromkeys(
        key for pattern in wanted for key in _matching(pattern, uploaded, automatic)
    )
    tracks = []
    for lang in languages:
        if lang in uploaded:
            tracks.append(Track(lang, _name(uploaded[lang], lang), UPLOADED))
            continue
        original = lang.endswith("-orig") or f"{lang}-orig" in automatic
        tracks.append(Track(lang, _name(automatic[lang], lang), AUTO if original else TRANSLATED))
    return sorted(tracks, key=lambda track: track.source != UPLOADED)


def wants_chat(raw: dict[str, Any], live_chat: bool) -> bool:
    return live_chat and bool((raw.get("subtitles") or {}).get(LIVE_CHAT))

"""YouTube link parsing, time helpers and lightweight video metadata."""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlparse

import httpx

log = logging.getLogger("podlens.youtube")

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}


class BadVideoLink(ValueError):
    pass


def parse_time(value: str | int | float | None) -> int | None:
    """Parse '90', '1:30', '01:02:03', '1m30s', '90s', '1h2m' into seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value).strip().lower()
    if not text:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return int(float(text))
    if re.fullmatch(r"\d{1,3}(:\d{1,2}){1,2}", text):
        parts = [int(p) for p in text.split(":")]
        seconds = 0
        for p in parts:
            seconds = seconds * 60 + p
        return seconds
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", text)
    if m and any(m.groups()):
        h, mi, s = (int(g) if g else 0 for g in m.groups())
        return h * 3600 + mi * 60 + s
    raise ValueError(f"Can't read the time '{value}'. Use a format like 2:30.")


def format_time(seconds: int | float | None) -> str:
    if seconds is None:
        return ""
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def parse_youtube_url(url: str) -> tuple[str, int | None]:
    """Return (video_id, start_seconds_from_link_or_None)."""
    raw = (url or "").strip()
    if _ID_RE.fullmatch(raw):
        return raw, None
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    query = parse_qs(parsed.query)
    video_id = None

    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/")[0]
    elif host in _YT_HOSTS:
        path = parsed.path.rstrip("/")
        if path == "/watch":
            video_id = (query.get("v") or [None])[0]
        else:
            m = re.match(r"^/(shorts|live|embed|v|e)/([^/?#]+)", path)
            if m:
                video_id = m.group(2)
    else:
        raise BadVideoLink("That doesn't look like a YouTube link.")

    if not video_id or not _ID_RE.fullmatch(video_id):
        raise BadVideoLink("Couldn't find a video ID in that YouTube link.")

    start = None
    t_value = (query.get("t") or query.get("start") or [None])[0]
    if t_value:
        try:
            start = parse_time(t_value)
        except ValueError:
            start = None
    return video_id, start


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _iso_duration_to_seconds(value: str) -> int | None:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not m:
        return None
    d, h, mi, s = (int(g) if g else 0 for g in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


async def fetch_metadata(video_id: str, youtube_api_key: str | None = None) -> dict:
    """Best-effort title, channel and thumbnail. Never raises."""
    meta: dict = {
        "id": video_id,
        "url": watch_url(video_id),
        "title": None,
        "author": None,
        "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        "published_at": None,
        "duration": None,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as http:
            if youtube_api_key:
                r = await http.get(
                    "https://www.googleapis.com/youtube/v3/videos",
                    params={"part": "snippet,contentDetails", "id": video_id, "key": youtube_api_key},
                )
                if r.status_code == 200 and r.json().get("items"):
                    item = r.json()["items"][0]
                    snippet = item.get("snippet", {})
                    meta["title"] = snippet.get("title")
                    meta["author"] = snippet.get("channelTitle")
                    meta["published_at"] = snippet.get("publishedAt")
                    meta["duration"] = _iso_duration_to_seconds(
                        item.get("contentDetails", {}).get("duration", "")
                    )
                    return meta
            r = await http.get(
                "https://www.youtube.com/oembed",
                params={"url": watch_url(video_id), "format": "json"},
            )
            if r.status_code == 200:
                data = r.json()
                meta["title"] = data.get("title")
                meta["author"] = data.get("author_name")
                meta["thumbnail"] = data.get("thumbnail_url") or meta["thumbnail"]
            elif r.status_code in (401, 403, 404):
                meta["unavailable"] = True
    except Exception as exc:  # metadata is optional
        log.info("metadata lookup failed for %s: %s", video_id, exc)
    return meta

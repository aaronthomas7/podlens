"""Runtime settings, read once from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def _str(name: str, default: str | None = None) -> str | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip()


DEFAULT_FALLBACK_MODELS = (
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
)

# Bump when prompts or the result shape change, so old cached results are not reused.
PIPELINE_VERSION = "1"


@dataclass(frozen=True)
class Settings:
    mock: bool
    api_key: str | None
    project: str | None
    location: str
    model: str
    fallback_models: tuple[str, ...]
    max_claims: int
    max_window_s: int
    verify_concurrency: int
    use_firestore: bool
    firestore_collection: str
    youtube_api_key: str | None
    rate_per_ip_hour: int
    rate_global_day: int
    agentic_long_videos: bool
    long_video_s: int
    thinking_level: str | None
    verify_backend: str

    @property
    def backend(self) -> str:
        if self.mock:
            return "mock"
        return "gemini-api" if self.api_key else "vertex"


def load_settings() -> Settings:
    fallback_raw = _str("GEMINI_FALLBACK_MODELS")
    fallback = (
        tuple(m.strip() for m in fallback_raw.split(",") if m.strip())
        if fallback_raw
        else DEFAULT_FALLBACK_MODELS
    )
    return Settings(
        mock=_bool("MOCK_MODE"),
        api_key=_str("GEMINI_API_KEY") or _str("GOOGLE_API_KEY"),
        project=_str("GOOGLE_CLOUD_PROJECT"),
        location=_str("GOOGLE_CLOUD_LOCATION", "global") or "global",
        model=_str("GEMINI_MODEL", fallback[0]) or fallback[0],
        fallback_models=fallback,
        max_claims=max(3, min(_int("MAX_CLAIMS", 12), 25)),
        max_window_s=max(60, _int("MAX_WINDOW_SECONDS", 1800)),
        verify_concurrency=max(1, min(_int("VERIFY_CONCURRENCY", 4), 10)),
        use_firestore=_bool("USE_FIRESTORE"),
        firestore_collection=_str("FIRESTORE_COLLECTION", "podlens_analyses")
        or "podlens_analyses",
        youtube_api_key=_str("YOUTUBE_API_KEY"),
        rate_per_ip_hour=max(1, _int("RATE_PER_IP_HOUR", 6)),
        rate_global_day=max(1, _int("RATE_GLOBAL_DAY", 60)),
        agentic_long_videos=_bool("AGENTIC_LONG_VIDEOS", True),
        long_video_s=max(120, _int("LONG_VIDEO_SECONDS", 600)),
        thinking_level=_str("THINKING_LEVEL"),
        verify_backend=(_str("VERIFY_BACKEND", "auto") or "auto").lower(),
    )

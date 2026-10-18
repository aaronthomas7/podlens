"""Runs one analysis end to end and emits progress events as it goes."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timezone

from . import mock
from .config import PIPELINE_VERSION, Settings
from .extract import extract_claims, plan_window
from .gemini import FriendlyError, Gemini, friendly
from .jobs import Job
from .scoring import score_claims, score_speakers
from .store import Store
from .verify import verify_claim
from .youtube import fetch_metadata, format_time

log = logging.getLogger("podlens.pipeline")

LANGUAGES = [
    "English",
    "Hindi",
    "Malayalam",
    "Tamil",
    "Telugu",
    "Kannada",
    "Bengali",
    "Marathi",
    "Bahasa Indonesia",
    "Japanese",
    "Korean",
    "Simplified Chinese",
]


def cache_key(video_id: str, start: int | None, end: int | None, language: str) -> str:
    return f"{video_id}|{start if start is not None else '-'}|{end if end is not None else '-'}|{language}|v{PIPELINE_VERSION}"


def analysis_id_for(key: str) -> str:
    return hashlib.sha1(key.encode()).hexdigest()[:12]


class Pipeline:
    def __init__(self, settings: Settings, store: Store, gemini: Gemini | None):
        self.settings = settings
        self.store = store
        self.gemini = gemini

    async def run(self, job: Job, video_id: str, start: int | None, end: int | None,
                  language: str, duration: float | None) -> None:
        t0 = time.monotonic()
        s = self.settings
        try:
            job.emit({"type": "status", "stage": "meta", "message": "Getting video details"})
            if s.mock:
                meta = {"id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}",
                        "title": "Sample video (mock mode)", "author": "PodLens demo",
                        "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                        "published_at": None, "duration": None}
            else:
                meta = await fetch_metadata(video_id, s.youtube_api_key)
            duration = duration or meta.get("duration")
            model = self.gemini.model if self.gemini else "mock"
            window = plan_window(start, end, duration, s, model)
            job.emit({"type": "meta", "analysis_id": job.analysis_id, "video": meta,
                      "window": _window_public(window), "model": model})

            job.emit({"type": "status", "stage": "watching",
                      "message": "Gemini is watching the video and listing the claims"})
            if s.mock:
                extraction, window = await mock.extract(video_id), window
            else:
                extraction, window = await extract_claims(self.gemini, s, video_id, window)
            claims = extraction["claims"]
            job.emit({"type": "claims", **extraction, "window": _window_public(window)})

            if claims:
                job.emit({"type": "status", "stage": "checking",
                          "message": f"Checking {len(claims)} claims with Google Search"})
                await self._verify_all(job, claims, extraction, meta, language)

            score = score_claims(claims)
            speakers = score_speakers(claims, extraction["speakers"])
            errors = sum(1 for c in claims if c.get("rule") == "error")
            analysis = {
                "id": job.analysis_id,
                "key": job.key,
                "version": PIPELINE_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "video": meta,
                "window": _window_public(window),
                "language": language,
                "summary": extraction["summary"],
                "spoken_language": extraction["language"],
                "topics": extraction["topics"],
                "speakers": speakers or extraction["speakers"],
                "opinions_skipped": extraction["opinions_skipped"],
                "claims": claims,
                "score": score,
                "model": model,
                "backend": s.backend,
                "mock": s.mock,
                "partial": errors > 0,
                "seconds_taken": round(time.monotonic() - t0, 1),
            }
            job.emit({"type": "score", "score": score, "speakers": analysis["speakers"]})
            if analysis["partial"]:
                # Some checks failed (e.g. quota); keep it for this session only so it gets re-run later.
                self.store._remember(analysis)
            else:
                await self.store.put(analysis)
            job.emit({"type": "done", "analysis": analysis})
        except Exception as exc:  # report every failure to the client
            if not isinstance(exc, FriendlyError):
                log.exception("analysis failed for %s", video_id)
            job.emit({"type": "error", "message": friendly(exc)})
        finally:
            job.finish()

    async def _verify_all(self, job: Job, claims: list[dict], extraction: dict, meta: dict, language: str) -> None:
        sem = asyncio.Semaphore(self.settings.verify_concurrency)
        labels = {sp["id"]: sp["label"] for sp in extraction["speakers"]}

        async def check(claim: dict) -> None:
            async with sem:
                ctx = {
                    "summary": extraction["summary"],
                    "speaker_label": labels.get(claim["speaker"], claim["speaker"]),
                    "published_at": meta.get("published_at"),
                }
                try:
                    if self.settings.mock:
                        result = await mock.verify(claim)
                    else:
                        result = await verify_claim(self.gemini, claim, ctx, language)
                except Exception as exc:
                    log.warning("verify failed for %s: %s", claim["id"], exc)
                    result = {
                        "verdict": "UNVERIFIABLE", "confidence": "low",
                        "summary": friendly(exc), "correction": "", "explanation": "",
                        "rule": "error", "sources": [], "search_queries": [], "suggestions_html": None,
                    }
                claim.update(result)
                job.emit({"type": "verdict", "claim_id": claim["id"], **result})

        await asyncio.gather(*(check(c) for c in claims))


def _window_public(window: dict) -> dict:
    auto = bool(window.get("auto_cap"))
    if auto:
        label = f"First {int(window['end']) // 60} minutes"
    elif window.get("end"):
        label = f"{format_time(window.get('start') or 0)}–{format_time(window['end'])}"
    else:
        label = "Whole video"
    return {
        "mode": window.get("mode"),
        "start": window.get("start") or 0,
        "end": window.get("end"),
        "auto": auto,
        "label": label,
        "note": window.get("note"),
    }

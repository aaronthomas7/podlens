"""PodLens web app: FastAPI backend + static frontend, built for Cloud Run."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import load_settings
from .gemini import Gemini
from .jobs import JobRegistry
from .pipeline import LANGUAGES, Pipeline, analysis_id_for, cache_key
from .ratelimit import RateLimiter
from .schemas import AnalyzeRequest
from .store import Store
from .youtube import BadVideoLink, parse_time, parse_youtube_url

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("podlens")

STATIC = Path(__file__).resolve().parent.parent / "static"

settings = load_settings()
store = Store(settings)
jobs = JobRegistry()
limiter = RateLimiter(settings.rate_per_ip_hour, settings.rate_global_day)
gemini: Gemini | None = None
if not settings.mock:
    try:
        gemini = Gemini(settings)
    except Exception as exc:  # surface config problems on /healthz instead of crashing
        log.error("Gemini client could not start: %s", exc)
pipeline = Pipeline(settings, store, gemini)

app = FastAPI(title="PodLens", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

NO_STORE = {"Cache-Control": "no-store"}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.get("/", include_in_schema=False)
@app.get("/a/{analysis_id}", include_in_schema=False)
async def index(analysis_id: str | None = None):
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
async def healthz():
    return {
        "ok": settings.mock or gemini is not None,
        "backend": settings.backend,
        "model": gemini.model if gemini else ("mock" if settings.mock else None),
        "firestore": store.fs is not None,
        "running_jobs": jobs.running,
    }


@app.get("/api/config")
async def config():
    return {
        "mock": settings.mock,
        "backend": settings.backend,
        "model": gemini.model if gemini else "mock",
        "languages": LANGUAGES,
        "max_window_minutes": settings.max_window_s // 60,
        "max_claims": settings.max_claims,
    }


@app.get("/api/recent")
async def recent():
    return JSONResponse(await store.recent(6), headers=NO_STORE)


@app.get("/api/analysis/{analysis_id}")
async def get_analysis(analysis_id: str):
    if not analysis_id.isalnum() or len(analysis_id) > 40:
        raise HTTPException(404, "Not found")
    analysis = await store.get(analysis_id)
    if not analysis:
        raise HTTPException(404, "This fact-check wasn't found. It may have expired.")
    return JSONResponse(analysis, headers=NO_STORE)


@app.get("/api/stream/{analysis_id}")
async def stream_existing(analysis_id: str):
    """Follow an analysis that is still running (e.g. a share link opened mid-check)."""
    job = jobs.by_id(analysis_id)
    if job is not None:
        return _ndjson(job.subscribe())
    analysis = await store.get(analysis_id)
    if analysis:
        return _ndjson(_single({"type": "done", "analysis": analysis, "cached": True}))
    raise HTTPException(404, "This fact-check wasn't found. It may have expired.")


def _ndjson(events):
    async def gen():
        async for event in events:
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


async def _single(event: dict):
    yield event


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest, request: Request):
    try:
        video_id, link_start = parse_youtube_url(req.url)
    except BadVideoLink as exc:
        raise HTTPException(400, str(exc))
    try:
        start = parse_time(req.start) if req.start else link_start
        end = parse_time(req.end) if req.end else None
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if start is not None and end is not None and end <= start:
        raise HTTPException(400, "The end time has to be after the start time.")
    language = req.language if req.language in LANGUAGES else "English"

    key = cache_key(video_id, start, end, language)
    analysis_id = analysis_id_for(key)

    cached = await store.get(analysis_id)
    if cached and not cached.get("partial"):
        return _ndjson(_single({"type": "done", "analysis": cached, "cached": True}))

    job = jobs.get(key)
    if job is None:
        if not settings.mock and gemini is None:
            raise HTTPException(503, "PodLens isn't connected to Gemini yet. Check the server setup.")
        limited = limiter.check(_client_ip(request))
        if limited:
            raise HTTPException(429, limited)
        job = jobs.create(key, analysis_id)
        job.task = asyncio.create_task(pipeline.run(job, video_id, start, end, language, req.duration))
        log.info("started analysis %s for %s", analysis_id, video_id)

    return _ndjson(job.subscribe())


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=NO_STORE)

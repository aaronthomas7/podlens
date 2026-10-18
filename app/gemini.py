"""Gemini client with model fallback, retries and friendly errors."""

from __future__ import annotations

import asyncio
import inspect
import logging
import random
from typing import Awaitable, Callable, TypeVar

from google import genai
from google.genai import errors

from .config import Settings

log = logging.getLogger("podlens.gemini")
T = TypeVar("T")

RETRYABLE = {429, 500, 502, 503, 504}


class FriendlyError(Exception):
    """An error whose message is safe and useful to show in the UI."""


def _detect_project() -> str | None:
    try:
        import google.auth

        _, project = google.auth.default()
        return project
    except Exception:
        return None


def friendly(exc: BaseException) -> str:
    if isinstance(exc, FriendlyError):
        return str(exc)
    if isinstance(exc, errors.APIError):
        code = getattr(exc, "code", None)
        msg = (getattr(exc, "message", "") or str(exc)).lower()
        if code == 429:
            return "Gemini is busy right now (quota reached). Please try again in a minute."
        if code == 403:
            return (
                "Gemini access was denied. Check that the Vertex AI API is enabled and the "
                "Cloud Run service account has the Vertex AI User role."
            )
        if code == 400 and any(w in msg for w in ("video", "youtube", "file", "uri", "url")):
            return (
                "Gemini couldn't open this video. It has to be a public YouTube video "
                "(not private, unlisted or age-restricted)."
            )
        if code == 404:
            return "The configured Gemini model isn't available in this project."
        if code and code >= 500:
            return "Gemini had a temporary problem. Please try again."
    return "Something went wrong while checking this video. Please try again."


class Gemini:
    def __init__(self, settings: Settings):
        self.settings = settings
        if settings.api_key:
            self.client = genai.Client(api_key=settings.api_key)
            self.vertex = False
        else:
            project = settings.project or _detect_project()
            self.client = genai.Client(
                vertexai=True, project=project, location=settings.location
            )
            self.vertex = True
        ordered = [settings.model] + [m for m in settings.fallback_models if m != settings.model]
        self.models: list[str] = ordered
        self._idx = 0
        self._lock = asyncio.Lock()

    @property
    def model(self) -> str:
        return self.models[self._idx]

    async def _advance_from(self, failed_model: str) -> bool:
        async with self._lock:
            if self.models[self._idx] != failed_model:
                return True  # another request already moved on
            if self._idx + 1 < len(self.models):
                self._idx += 1
                log.warning("Model %s unavailable, falling back to %s", failed_model, self.model)
                return True
            return False

    async def call(self, fn: Callable[[str], Awaitable[T]], *, attempts: int = 2) -> T:
        """Run fn(model) with retries on transient errors.

        A model that is missing (404) is dropped for good. A model that keeps failing
        with server errors is skipped for this call only, and the next model is tried.
        """
        tried: set[str] = set()
        last_exc: Exception | None = None
        while True:
            remaining = [m for m in self.models[self._idx :] if m not in tried]
            if not remaining:
                if last_exc:
                    raise last_exc
                raise FriendlyError("No Gemini model is available right now. Please try again.")
            current = remaining[0]
            tried.add(current)
            try:
                return await self._with_retries(fn, current, attempts)
            except errors.APIError as exc:
                last_exc = exc
                code = getattr(exc, "code", None)
                log.warning("Gemini call failed on %s (%s): %s", current, code, getattr(exc, "message", exc))
                if code == 404:
                    if current == self.model:
                        await self._advance_from(current)
                    continue
                if code in RETRYABLE:
                    continue
                raise

    async def _with_retries(self, fn, model: str, attempts: int):
        delay = 1.5
        for attempt in range(1, attempts + 1):
            try:
                return await fn(model)
            except errors.APIError as exc:
                code = getattr(exc, "code", None)
                if code in RETRYABLE and attempt < attempts:
                    wait = delay + random.uniform(0, delay / 2)
                    log.info("Gemini %s on %s, retrying in %.1fs: %s", code, model, wait, getattr(exc, "message", exc))
                    await asyncio.sleep(wait)
                    delay *= 2.5
                    continue
                raise

    async def stream_text(self, *, model: str, contents, config) -> tuple[str, object | None]:
        """Stream a response and return (full_text, last_chunk)."""
        stream = self.client.aio.models.generate_content_stream(
            model=model, contents=contents, config=config
        )
        if inspect.isawaitable(stream):
            stream = await stream
        pieces: list[str] = []
        last = None
        async for chunk in stream:
            last = chunk
            for cand in chunk.candidates or []:
                for part in (cand.content.parts if cand.content else None) or []:
                    if part.text and not part.thought:
                        pieces.append(part.text)
        return "".join(pieces), last

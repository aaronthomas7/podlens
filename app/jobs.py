"""In-flight analyses. Late joiners and reconnects replay every event so far,
and two people checking the same video share one Gemini run."""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator


class Job:
    def __init__(self, key: str, analysis_id: str):
        self.key = key
        self.analysis_id = analysis_id
        self.events: list[dict] = []
        self.done = False
        self.finished_at: float | None = None
        self._changed = asyncio.Event()
        self.task: asyncio.Task | None = None

    def emit(self, event: dict) -> None:
        self.events.append(event)
        changed, self._changed = self._changed, asyncio.Event()
        changed.set()

    def finish(self) -> None:
        self.done = True
        self.finished_at = time.monotonic()
        changed, self._changed = self._changed, asyncio.Event()
        changed.set()

    async def subscribe(self, heartbeat: float = 10.0) -> AsyncIterator[dict]:
        i = 0
        while True:
            while i < len(self.events):
                yield self.events[i]
                i += 1
            if self.done:
                return
            waiter = self._changed
            try:
                await asyncio.wait_for(waiter.wait(), timeout=heartbeat)
            except asyncio.TimeoutError:
                yield {"type": "ping"}


class JobRegistry:
    def __init__(self, keep_seconds: float = 600):
        self.jobs: dict[str, Job] = {}
        self.keep_seconds = keep_seconds

    def _sweep(self) -> None:
        now = time.monotonic()
        for key in [k for k, j in self.jobs.items() if j.done and j.finished_at and now - j.finished_at > self.keep_seconds]:
            self.jobs.pop(key, None)

    def get(self, key: str) -> Job | None:
        self._sweep()
        job = self.jobs.get(key)
        if job and job.done and any(e.get("type") == "error" for e in job.events):
            # Don't replay failures forever; let the next request try again.
            self.jobs.pop(key, None)
            return None
        return job

    def create(self, key: str, analysis_id: str) -> Job:
        job = Job(key, analysis_id)
        self.jobs[key] = job
        return job

    def by_id(self, analysis_id: str) -> Job | None:
        self._sweep()
        for job in self.jobs.values():
            if job.analysis_id == analysis_id:
                return job
        return None

    @property
    def running(self) -> int:
        return sum(1 for j in self.jobs.values() if not j.done)

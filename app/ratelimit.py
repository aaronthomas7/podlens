"""Small in-memory limits on fresh analyses, to keep a public demo affordable.
Cached results are never limited."""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, per_ip_hour: int, global_day: int):
        self.per_ip_hour = per_ip_hour
        self.global_day = global_day
        self.by_ip: dict[str, deque] = defaultdict(deque)
        self.all: deque = deque()

    @staticmethod
    def _trim(q: deque, window: float, now: float) -> None:
        while q and now - q[0] > window:
            q.popleft()

    def check(self, ip: str) -> str | None:
        """Return an error message if over a limit, else record the hit and return None."""
        now = time.time()
        q = self.by_ip[ip]
        self._trim(q, 3600, now)
        self._trim(self.all, 86400, now)
        if len(self.all) >= self.global_day:
            return "PodLens has hit its daily limit for new checks. Recent results still work."
        if len(q) >= self.per_ip_hour:
            return "You've started a lot of checks this hour. Please wait a bit and try again."
        q.append(now)
        self.all.append(now)
        return None

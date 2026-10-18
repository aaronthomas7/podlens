"""Finished analyses: in-memory LRU, plus Firestore when enabled.

Firestore lets a result outlive the Cloud Run instance, so share links and
repeat checks of the same video work for everyone, instantly.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict

from .config import Settings

log = logging.getLogger("podlens.store")


class Store:
    def __init__(self, settings: Settings, limit: int = 200):
        self.settings = settings
        self.limit = limit
        self.mem: OrderedDict[str, dict] = OrderedDict()
        self.fs = None
        if settings.use_firestore and not settings.mock:
            try:
                from google.cloud import firestore

                self.fs = firestore.AsyncClient(project=settings.project) if settings.project else firestore.AsyncClient()
                self.col = self.fs.collection(settings.firestore_collection)
                log.info("Firestore cache enabled (%s)", settings.firestore_collection)
            except Exception as exc:
                log.warning("Firestore disabled: %s", exc)
                self.fs = None

    def _remember(self, analysis: dict) -> None:
        self.mem[analysis["id"]] = analysis
        self.mem.move_to_end(analysis["id"])
        while len(self.mem) > self.limit:
            self.mem.popitem(last=False)

    async def get(self, analysis_id: str) -> dict | None:
        if analysis_id in self.mem:
            self.mem.move_to_end(analysis_id)
            return self.mem[analysis_id]
        if self.fs is None:
            return None
        try:
            doc = await asyncio.wait_for(self.col.document(analysis_id).get(), timeout=6)
            if doc.exists:
                data = doc.to_dict().get("analysis")
                if data:
                    self._remember(data)
                    return data
        except Exception as exc:
            log.warning("Firestore read failed: %s", exc)
        return None

    async def put(self, analysis: dict) -> None:
        self._remember(analysis)
        if self.fs is None:
            return
        try:
            await asyncio.wait_for(
                self.col.document(analysis["id"]).set(
                    {
                        "analysis": analysis,
                        "created_at": analysis["created_at"],
                        "video_id": analysis["video"]["id"],
                        "title": analysis["video"].get("title"),
                        "score": analysis["score"].get("value"),
                    }
                ),
                timeout=8,
            )
        except Exception as exc:
            log.warning("Firestore write failed: %s", exc)

    async def recent(self, n: int = 6) -> list[dict]:
        items: list[dict] = []
        if self.fs is not None:
            try:
                from google.cloud import firestore

                query = self.col.order_by("created_at", direction=firestore.Query.DESCENDING).limit(n * 2)
                docs = await asyncio.wait_for(query.get(), timeout=6)
                items = [d.to_dict().get("analysis") for d in docs]
                items = [a for a in items if a]
            except Exception as exc:
                log.warning("Firestore recent failed: %s", exc)
        if not items:
            items = sorted(self.mem.values(), key=lambda a: a["created_at"], reverse=True)
        out, seen = [], set()
        for a in items:
            vid = a["video"]["id"]
            if vid in seen:
                continue
            seen.add(vid)
            out.append(
                {
                    "id": a["id"],
                    "title": a["video"].get("title") or "YouTube video",
                    "author": a["video"].get("author"),
                    "thumbnail": a["video"].get("thumbnail"),
                    "score": a["score"].get("value"),
                    "score_label": a["score"].get("label"),
                    "claims": a["score"].get("total"),
                    "created_at": a["created_at"],
                    "mock": a.get("mock", False),
                }
            )
            if len(out) >= n:
                break
        return out

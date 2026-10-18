"""Trust score: transparent arithmetic over verdicts, never a model's opinion."""

from __future__ import annotations

VERDICT_VALUE = {"TRUE": 1.0, "OUTDATED": 0.5, "MISLEADING": 0.3, "FALSE": 0.0}
IMPORTANCE_WEIGHT = {"high": 3.0, "medium": 2.0, "low": 1.0}

METHOD = (
    "Each checked claim counts True = 100, Outdated = 50, Misleading = 30, False = 0. "
    "High-importance claims count 3x and medium 2x. Claims PodLens couldn't verify are "
    "shown but left out of the score."
)


def _label(score: int | None) -> str:
    if score is None:
        return "Not enough checkable claims"
    if score >= 80:
        return "Mostly accurate"
    if score >= 55:
        return "Mixed accuracy"
    if score >= 30:
        return "Often inaccurate"
    return "Mostly inaccurate"


def score_claims(claims: list[dict]) -> dict:
    counts = {k: 0 for k in ("TRUE", "MISLEADING", "FALSE", "OUTDATED", "UNVERIFIABLE")}
    total_w = 0.0
    got = 0.0
    scored = 0
    for c in claims:
        v = c.get("verdict")
        if v not in counts:
            continue
        counts[v] += 1
        if v in VERDICT_VALUE:
            w = IMPORTANCE_WEIGHT.get(c.get("importance"), 2.0)
            total_w += w
            got += w * VERDICT_VALUE[v]
            scored += 1
    value = round(100 * got / total_w) if total_w else None
    return {
        "value": value,
        "label": _label(value),
        "counts": counts,
        "scored": scored,
        "total": sum(counts.values()),
        "method": METHOD,
    }


def score_speakers(claims: list[dict], speakers: list[dict]) -> list[dict]:
    out = []
    for s in speakers:
        mine = [c for c in claims if c.get("speaker") == s["id"]]
        if not mine:
            continue
        sc = score_claims(mine)
        out.append({**s, "score": sc["value"], "label_text": sc["label"], "claims": len(mine), "counts": sc["counts"]})
    return out

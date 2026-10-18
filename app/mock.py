"""Mock mode: realistic fake output so the UI can be built and tested without
Google Cloud. Everything produced here is labelled as sample data."""

from __future__ import annotations

import asyncio
import random

_SPEAKERS = [{"id": "S1", "label": "Host"}, {"id": "S2", "label": "Guest"}]

_CLAIMS = [
    ("00:15", "S1", "high", "science",
     "Humans use only 10 percent of their brains.",
     "FALSE", "high",
     "Brain imaging shows people use virtually all of their brain, just not all regions at once.",
     "Scans show activity across the whole brain over a normal day.",
     [("nih.gov", "Brain Basics"), ("britannica.com", "Ten percent of the brain myth")]),
    ("00:48", "S2", "high", "health",
     "Antibiotics do not work against viral infections such as the common cold.",
     "TRUE", "high",
     "Health agencies agree antibiotics treat bacteria, not viruses like the cold or flu.",
     "",
     [("who.int", "Antibiotic resistance"), ("cdc.gov", "Antibiotics and viruses")]),
    ("01:20", "S1", "medium", "science",
     "The Great Wall of China can be seen with the naked eye from the Moon.",
     "FALSE", "high",
     "Astronauts report the wall is not visible from the Moon; it is too narrow.",
     "From the Moon, no individual human structure is visible to the naked eye.",
     [("nasa.gov", "Great Wall from space"), ("scientificamerican.com", "Is the Great Wall visible?")]),
    ("02:05", "S2", "high", "health",
     "Drinking hot water with lemon every morning cures type 2 diabetes.",
     "FALSE", "high",
     "No evidence shows lemon water cures diabetes; treatment relies on diet, exercise and medicine.",
     "Diabetes is managed with lifestyle changes and prescribed medication.",
     [("who.int", "Diabetes fact sheet"), ("mayoclinic.org", "Type 2 diabetes treatment")]),
    ("02:40", "S2", "medium", "health",
     "Taking large doses of vitamin C prevents colds for everyone.",
     "MISLEADING", "medium",
     "Regular vitamin C doesn't prevent colds for most people; it may slightly shorten them.",
     "Reviews find little effect on catching colds in the general population.",
     [("cochranelibrary.com", "Vitamin C for the common cold"), ("nih.gov", "Vitamin C fact sheet")]),
    ("03:10", "S1", "low", "science",
     "Pluto is the ninth planet of the Solar System.",
     "OUTDATED", "high",
     "Pluto was reclassified as a dwarf planet in 2006, so this is no longer true.",
     "Since 2006 the Solar System has eight planets; Pluto is a dwarf planet.",
     [("nasa.gov", "Pluto overview"), ("britannica.com", "Pluto")]),
    ("03:55", "S1", "medium", "history",
     "Mount Everest is the highest mountain above sea level, at about 8,849 metres.",
     "TRUE", "high",
     "Everest's official height is 8,848.86 m, measured jointly by Nepal and China in 2020.",
     "",
     [("britannica.com", "Mount Everest"), ("nationalgeographic.com", "Everest height")]),
    ("04:30", "S2", "low", "other",
     "This herbal tea recipe was created in 1820 by a village doctor in Kerala.",
     "UNVERIFIABLE", "low",
     "PodLens couldn't find reliable sources for this claim, so it isn't scored.",
     "",
     []),
]


def _kind(domain: str) -> str:
    from .sources import classify

    return classify(domain)


async def extract(video_id: str) -> dict:
    await asyncio.sleep(2.0)
    claims = []
    for i, (ts, spk, imp, cat, text, *_rest) in enumerate(_CLAIMS, 1):
        m, s = ts.split(":")
        claims.append(
            {
                "id": f"c{i}",
                "seconds": int(m) * 60 + int(s),
                "timestamp": ts,
                "speaker": spk,
                "quote": text,
                "quote_english": text,
                "claim": text,
                "category": cat,
                "importance": imp,
                "on_screen": False,
            }
        )
    return {
        "summary": "Sample data: a two-person chat mixing common myths with real facts.",
        "language": "English",
        "topics": ["health myths", "science", "sample"],
        "speakers": list(_SPEAKERS),
        "claims": claims,
        "opinions_skipped": 5,
    }


async def verify(claim: dict) -> dict:
    await asyncio.sleep(random.uniform(0.6, 1.8))
    row = _CLAIMS[int(claim["id"][1:]) - 1]
    verdict, conf, summary, correction, sources = row[5], row[6], row[7], row[8], row[9]
    from .sources import KIND_LABELS

    srcs = []
    for domain, title in sources:
        k = _kind(domain)
        srcs.append({"title": title, "domain": domain, "uri": f"https://{domain}/", "kind": k, "kind_label": KIND_LABELS[k]})
    return {
        "verdict": verdict,
        "confidence": conf,
        "summary": summary,
        "correction": correction,
        "explanation": "This is sample text from mock mode. Run with Gemini to get real evidence.",
        "rule": "no_sources" if not sources else None,
        "sources": srcs,
        "search_queries": [claim["claim"][:60]],
        "suggestions_html": None,
        "model": "mock",
    }

"""Classify evidence sources so people can see how strong the backing is.

This is deterministic on purpose: the model chooses what to search,
plain code decides which sources count as official, research and so on.
"""

from __future__ import annotations

import re

# Never used as evidence: the video platform itself and social media.
EXCLUDED_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "tiktok.com",
    "threads.net",
    "reddit.com",
    "quora.com",
    "pinterest.com",
    "linkedin.com",
    "sharechat.com",
    "moj.app",
)

_OFFICIAL_SUFFIXES = (
    ".gov",
    ".gov.in",
    ".nic.in",
    ".gov.uk",
    ".gov.au",
    ".gov.sg",
    ".gov.my",
    ".gov.ph",
    ".go.id",
    ".go.jp",
    ".go.kr",
    ".go.th",
    ".gov.cn",
    ".govt.nz",
    ".gc.ca",
    ".int",
    ".europa.eu",
)
_OFFICIAL_DOMAINS = {
    "rbi.org.in",
    "sebi.gov.in",
    "pib.gov.in",
    "icmr.gov.in",
    "un.org",
    "worldbank.org",
    "imf.org",
    "oecd.org",
    "ipcc.ch",
    "who.int",
    "unicef.org",
    "mas.gov.sg",
    "bis.org",
}
_RESEARCH_DOMAINS = {
    "nature.com",
    "science.org",
    "thelancet.com",
    "nejm.org",
    "bmj.com",
    "jamanetwork.com",
    "cell.com",
    "sciencedirect.com",
    "springer.com",
    "link.springer.com",
    "wiley.com",
    "onlinelibrary.wiley.com",
    "plos.org",
    "journals.plos.org",
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "cochranelibrary.com",
    "arxiv.org",
    "mayoclinic.org",
    "clevelandclinic.org",
    "hopkinsmedicine.org",
    "health.harvard.edu",
    "britannica.com",
}
_RESEARCH_SUFFIXES = (".edu", ".ac.in", ".ac.uk", ".edu.au", ".ac.jp", ".edu.sg", ".ac.kr")
_FACTCHECK_DOMAINS = {
    "factcheck.org",
    "snopes.com",
    "fullfact.org",
    "politifact.com",
    "boomlive.in",
    "altnews.in",
    "factly.in",
    "newschecker.in",
    "vishvasnews.com",
    "thequint.com",
    "afp.com",
    "factcheck.afp.com",
    "factcheckerlab.com",
}
_NEWS_DOMAINS = {
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "thehindu.com",
    "indianexpress.com",
    "hindustantimes.com",
    "livemint.com",
    "business-standard.com",
    "economictimes.indiatimes.com",
    "timesofindia.indiatimes.com",
    "ndtv.com",
    "theguardian.com",
    "nytimes.com",
    "washingtonpost.com",
    "bloomberg.com",
    "ft.com",
    "cnbc.com",
    "straitstimes.com",
    "channelnewsasia.com",
    "scmp.com",
    "japantimes.co.jp",
    "nikkei.com",
    "abc.net.au",
    "aljazeera.com",
    "npr.org",
    "theprint.in",
    "scroll.in",
    "moneycontrol.com",
    "manoramaonline.com",
    "mathrubhumi.com",
}

KIND_LABELS = {
    "official": "Official",
    "research": "Research",
    "factcheck": "Fact-checker",
    "news": "News",
    "reference": "Reference",
    "other": "Web",
}


def normalize_domain(value: str | None) -> str:
    if not value:
        return ""
    text = value.strip().lower()
    text = re.sub(r"^https?://", "", text)
    text = text.split("/")[0].split("?")[0]
    if text.startswith("www."):
        text = text[4:]
    return text


def _matches(domain: str, candidates: set[str] | tuple[str, ...]) -> bool:
    return any(domain == c or domain.endswith("." + c) for c in candidates)


def is_excluded(domain: str) -> bool:
    return bool(domain) and _matches(domain, EXCLUDED_DOMAINS)


def classify(domain: str) -> str:
    if not domain:
        return "other"
    if domain.endswith(_OFFICIAL_SUFFIXES) or _matches(domain, _OFFICIAL_DOMAINS):
        return "official"
    if _matches(domain, _FACTCHECK_DOMAINS):
        return "factcheck"
    if domain.endswith(_RESEARCH_SUFFIXES) or _matches(domain, _RESEARCH_DOMAINS):
        return "research"
    if _matches(domain, _NEWS_DOMAINS):
        return "news"
    if domain.endswith("wikipedia.org"):
        return "reference"
    return "other"


def strong_count(sources: list[dict]) -> int:
    return sum(1 for s in sources if s.get("kind") in {"official", "research", "factcheck"})

"""Shapes shared by the pipeline.

The Extraction* models are also sent to Gemini as the response schema,
so they stay simple: strings, ints, bools, lists and Literal enums only.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "health",
    "finance",
    "science",
    "history",
    "politics",
    "statistics",
    "current_events",
    "other",
]
Importance = Literal["high", "medium", "low"]
VerdictLabel = Literal["TRUE", "MISLEADING", "FALSE", "OUTDATED", "UNVERIFIABLE"]
Confidence = Literal["high", "medium", "low"]

VERDICTS: tuple[str, ...] = ("TRUE", "MISLEADING", "FALSE", "OUTDATED", "UNVERIFIABLE")


class ExtractedSpeaker(BaseModel):
    id: str = Field(description="Speaker id such as S1, S2.")
    label: str = Field(
        description=(
            "Short role label (host, guest, narrator, interviewer, caller). Add a "
            "name only if it is clearly said or shown in the video."
        )
    )


class ExtractedClaim(BaseModel):
    timestamp: str = Field(
        description="Absolute time in the full video when the claim is first made, MM:SS or H:MM:SS."
    )
    speaker: str = Field(description="Speaker id from the speakers list, or 'on-screen'.")
    quote: str = Field(description="Exact words in the original language.")
    quote_english: str = Field(description="English translation of the quote (repeat it if already English).")
    claim: str = Field(
        description=(
            "Standalone English restatement that can be fact-checked without watching: "
            "resolve pronouns, include who, what, when, where and any numbers."
        )
    )
    category: Category
    importance: Importance
    on_screen: bool = Field(description="True if the claim appears as on-screen text or graphics.")


class ExtractionResult(BaseModel):
    summary: str = Field(description="One neutral sentence describing what the video is about.")
    language: str = Field(description="Main spoken language, in English, e.g. 'Hindi'.")
    topics: list[str] = Field(description="Up to 4 short topic tags.")
    speakers: list[ExtractedSpeaker]
    claims: list[ExtractedClaim]
    opinions_skipped: int = Field(description="How many opinions or non-factual statements were skipped.")


class VerdictResult(BaseModel):
    verdict: VerdictLabel
    confidence: Confidence
    summary: str
    correction: str = ""
    explanation: str = ""


class AnalyzeRequest(BaseModel):
    url: str = Field(min_length=5, max_length=500)
    start: str | None = Field(default=None, max_length=12)
    end: str | None = Field(default=None, max_length=12)
    language: str = Field(default="English", max_length=40)
    duration: float | None = Field(default=None, ge=0, le=60 * 60 * 24)

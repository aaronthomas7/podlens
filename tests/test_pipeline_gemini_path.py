"""Runs the real (non-mock) pipeline against a fake Gemini transport built from
real SDK response types, so request building and response parsing are exercised."""

import asyncio
import json
from dataclasses import replace

import pytest
from google.genai import errors, types

from app.config import load_settings
from app.extract import plan_window, postprocess, supports_agentic, _video_part
from app.gemini import Gemini
from app.jobs import JobRegistry
from app.pipeline import Pipeline, analysis_id_for, cache_key
from app.schemas import ExtractionResult
from app.store import Store

EXTRACTION = {
    "summary": "A Malayalam health podcast about home remedies.",
    "language": "Malayalam",
    "topics": ["health", "diet"],
    "speakers": [{"id": "S1", "label": "Host"}, {"id": "S2", "label": "Guest (Dr. Anil, introduced at 00:12)"}],
    "claims": [
        {"timestamp": "01:10", "speaker": "S2", "quote": "ചൂടുവെള്ളം പ്രമേഹം മാറ്റും", "quote_english": "Hot water cures diabetes",
         "claim": "Drinking hot water cures type 2 diabetes.", "category": "health", "importance": "high", "on_screen": False},
        {"timestamp": "00:20", "speaker": "S1", "quote": "Kerala has 14 districts", "quote_english": "Kerala has 14 districts",
         "claim": "Kerala has 14 districts.", "category": "statistics", "importance": "low", "on_screen": False},
        {"timestamp": "00:21", "speaker": "S1", "quote": "Kerala has fourteen districts", "quote_english": "Kerala has fourteen districts",
         "claim": "Kerala has 14 districts.", "category": "statistics", "importance": "low", "on_screen": False},
        {"timestamp": "02:00", "speaker": "on-screen", "quote": "Sugar-free tea", "quote_english": "Sugar-free tea",
         "claim": "This tea brand was founded in 1820.", "category": "history", "importance": "low", "on_screen": True},
    ],
    "opinions_skipped": 3,
}

VERDICTS = {
    "Drinking hot water cures type 2 diabetes.": ('{"verdict":"FALSE","confidence":"high","summary":"No evidence.","correction":"Managed with diet and medicine.","explanation":"WHO says..."}', [("who.int",), ("mayoclinic.org",)]),
    "Kerala has 14 districts.": ('```json\n{"verdict":"TRUE","confidence":"high","summary":"Correct.","correction":"","explanation":"Official list."}\n```', [("kerala.gov.in",)]),
    "This tea brand was founded in 1820.": ('{"verdict":"FALSE","confidence":"low","summary":"Probably not.","correction":"","explanation":""}', []),
}


def _resp(text, chunks=()):
    return types.GenerateContentResponse.model_validate(
        {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": text}]},
                    "finish_reason": "STOP",
                    "grounding_metadata": {
                        "web_search_queries": ["q"],
                        "grounding_chunks": [{"web": {"uri": f"https://redirect/{c[0]}", "title": c[0]}} for c in chunks],
                    },
                }
            ]
        }
    )


class FakeModels:
    def __init__(self, fail_first_model=None, fail_code=404):
        self.stream_calls = []
        self.calls = []
        self.fail_first_model = fail_first_model
        self.fail_code = fail_code

    async def generate_content(self, *, model, contents, config):
        if not isinstance(contents, str):  # extraction: video + instruction
            self.stream_calls.append((model, contents, config))
            if self.fail_first_model and model == self.fail_first_model:
                raise errors.APIError(self.fail_code, {"error": {"code": self.fail_code, "message": "boom", "status": "X"}})
            return _resp(json.dumps(EXTRACTION, ensure_ascii=False))
        self.calls.append((model, contents, config))
        claim_line = contents.splitlines()[0].removeprefix("Claim to check: ")
        text, chunks = VERDICTS[claim_line]
        return _resp(text, chunks)


@pytest.fixture
def settings():
    return replace(load_settings(), mock=False, api_key="test-key", model="gemini-3.8-flash", use_firestore=False)


async def _no_sleep(*_a, **_k):
    return None


def make_gemini(settings, fake):
    g = Gemini(settings)
    g.client = type("C", (), {"aio": type("A", (), {"models": fake})()})()
    return g


def run_pipeline(settings, gemini, duration=240):
    store = Store(settings)
    pipe = Pipeline(settings, store, gemini)
    jobs = JobRegistry()
    key = cache_key("dQw4w9WgXcQ", None, None, "English")
    job = jobs.create(key, analysis_id_for(key))

    async def go():
        events = []
        task = asyncio.create_task(pipe.run(job, "dQw4w9WgXcQ", None, None, "English", duration))
        async for ev in job.subscribe(heartbeat=5):
            events.append(ev)
        await task
        return events

    return asyncio.run(go()), store


def test_full_pipeline_with_fake_gemini(settings, monkeypatch):
    async def no_meta(video_id, key=None):
        return {"id": video_id, "url": "u", "title": "T", "author": "A", "thumbnail": None, "published_at": None, "duration": None}

    monkeypatch.setattr("app.pipeline.fetch_metadata", no_meta)
    fake = FakeModels()
    events, store = run_pipeline(settings, make_gemini(settings, fake))
    types_seen = [e["type"] for e in events]
    assert types_seen[0] == "status" and types_seen[-1] == "done"
    assert types_seen.count("verdict") == 3  # duplicate Kerala claim merged

    a = events[-1]["analysis"]
    by_claim = {c["claim"]: c for c in a["claims"]}
    assert [c["timestamp"] for c in a["claims"]] == ["00:20", "01:10", "02:00"]
    assert by_claim["Drinking hot water cures type 2 diabetes."]["verdict"] == "FALSE"
    assert by_claim["Drinking hot water cures type 2 diabetes."]["sources"][0]["domain"] == "who.int"
    assert by_claim["Kerala has 14 districts."]["verdict"] == "TRUE"
    tea = by_claim["This tea brand was founded in 1820."]
    assert tea["verdict"] == "UNVERIFIABLE" and tea["rule"] == "no_sources" and tea["model_verdict"] == "FALSE"
    assert tea["speaker"] == "on-screen"
    assert a["score"]["value"] == 25  # TRUE low (1) + FALSE high (3) -> 1/4
    assert a["spoken_language"] == "Malayalam" and a["window"]["label"] == "Whole video"
    assert a["partial"] is False

    # Request building: YouTube URL as file data, schema-constrained JSON, search tool on checks.
    model, contents, config = fake.stream_calls[0]
    assert model == "gemini-3.8-flash"
    assert contents.parts[0].file_data.file_uri == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert config.response_mime_type == "application/json" and config.response_schema is ExtractionResult
    _, _, vconfig = fake.calls[0]
    assert vconfig.tools[0].google_search is not None
    assert vconfig.tools[0].google_search.exclude_domains is None  # filtering happens after the search

    import asyncio as _a
    assert _a.run(store.get(a["id"]))["id"] == a["id"]


@pytest.mark.parametrize("code", [404, 500])
def test_model_fallback(settings, monkeypatch, code):
    async def no_meta(video_id, key=None):
        return {"id": video_id, "url": "u", "title": "T", "author": None, "thumbnail": None, "published_at": None, "duration": None}

    monkeypatch.setattr("app.pipeline.fetch_metadata", no_meta)
    monkeypatch.setattr("app.gemini.asyncio.sleep", _no_sleep)
    fake = FakeModels(fail_first_model="gemini-3.8-flash", fail_code=code)
    gemini = make_gemini(settings, fake)
    events, _ = run_pipeline(settings, gemini)
    assert events[-1]["type"] == "done"
    models_used = [c[0] for c in fake.stream_calls]
    assert models_used[-1] == "gemini-3.6-flash" and models_used[0] == "gemini-3.8-flash"
    # 404 drops the model for good; a server error only skips it for that call
    assert gemini.model == ("gemini-3.6-flash" if code == 404 else "gemini-3.8-flash")


def test_plan_window_cases(settings):
    s = replace(settings, max_window_s=1800)
    assert plan_window(None, None, 600, s, "gemini-3.8-flash")["clip"] is False
    long = plan_window(None, None, 7200, s, "gemini-3.8-flash")
    assert long["mode"] == "agentic"
    assert plan_window(None, None, 7200, s, "gemini-3.5-flash")["mode"] == "static"
    capped = plan_window(None, None, None, s, "gemini-3.8-flash")
    assert capped["end"] == 1800 and capped["auto_cap"]
    user = plan_window(60, None, 7200, s, "gemini-3.8-flash")
    assert (user["start"], user["end"], user["clip"]) == (60, 1860, True)
    assert supports_agentic("gemini-4-argon") and not supports_agentic("gemini-2.5-flash")


def test_postprocess_relative_timestamps_and_limits():
    raw = ExtractionResult.model_validate(
        {**EXTRACTION, "claims": [
            {**EXTRACTION["claims"][0], "timestamp": "00:30"},
            {**EXTRACTION["claims"][1], "timestamp": "01:00"},
        ]}
    )
    out = postprocess(raw, {"start": 600, "end": 900}, max_claims=12)
    assert [c["seconds"] for c in out["claims"]] == [630, 660]
    keep = postprocess(ExtractionResult.model_validate(EXTRACTION), {"start": 0}, max_claims=1)
    assert len(keep["claims"]) == 1 and keep["claims"][0]["importance"] == "high"


@pytest.mark.parametrize("backend", ["mldev", "vertex"])
def test_requests_serialize_for_both_backends(backend):
    """The SDK must accept our video part and search config on each backend."""
    from google import genai
    from google.genai import _common, models

    if backend == "mldev":
        client = genai.Client(api_key="x")
        convert = models._GenerateContentParameters_to_mldev
    else:
        try:
            client = genai.Client(vertexai=True, project="demo-project", location="global")
        except Exception as exc:  # no credentials in CI
            pytest.skip(f"vertex client unavailable: {exc}")
        convert = models._GenerateContentParameters_to_vertex

    for window in (
        {"mode": "static", "clip": True, "start": 30, "end": 600},
        {"mode": "agentic", "clip": False, "start": 0, "end": None},
    ):
        params = types._GenerateContentParameters(
            model="gemini-3.8-flash",
            contents=[types.Content(role="user", parts=[_video_part("dQw4w9WgXcQ", window), types.Part(text="go")])],
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=ExtractionResult),
        )
        body = _common.convert_to_dict(convert(client._api_client, params))
        part = body["contents"][0]["parts"][0]
        assert json.dumps(part["fileData"]).count("watch?v=dQw4w9WgXcQ") == 1
        if window["mode"] == "agentic":
            assert part["mediaProcessing"] == "AGENTIC"
            assert "videoMetadata" not in part
        else:
            assert "30s" in json.dumps(part["videoMetadata"]) and "600s" in json.dumps(part["videoMetadata"])
            assert "mediaProcessing" not in part

    search = types.GoogleSearch(exclude_domains=["youtube.com"]) if backend == "vertex" else types.GoogleSearch()
    params = types._GenerateContentParameters(
        model="gemini-3.8-flash", contents="check", config=types.GenerateContentConfig(tools=[types.Tool(google_search=search)])
    )
    body = _common.convert_to_dict(convert(client._api_client, params))
    text = json.dumps(body)
    assert "googleSearch" in text
    if backend == "vertex":
        assert "youtube.com" in text

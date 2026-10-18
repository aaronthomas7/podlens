import json

import pytest
from google.genai import types

from app.schemas import VerdictResult
from app.scoring import score_claims, score_speakers
from app.sources import classify, is_excluded, normalize_domain
from app.verify import apply_rules, extract_grounding, parse_verdict, safe_entry_point


def grounded_response(text: str, chunks: list[tuple[str, str]], queries=("q1",), html="<style>.c{}</style><div class='c'>chips</div>"):
    return types.GenerateContentResponse.model_validate(
        {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": text}]},
                    "finish_reason": "STOP",
                    "grounding_metadata": {
                        "web_search_queries": list(queries),
                        "search_entry_point": {"rendered_content": html},
                        "grounding_chunks": [
                            {"web": {"uri": f"https://vertexaisearch.cloud.google.com/grounding-api-redirect/{i}", "title": title}}
                            for i, (title, _) in enumerate(chunks)
                        ],
                    },
                }
            ]
        }
    )


def test_parse_verdict_clean_and_fenced():
    v = parse_verdict('{"verdict":"FALSE","confidence":"high","summary":"s","correction":"c","explanation":"e"}')
    assert v.verdict == "FALSE" and v.confidence == "high" and v.correction == "c"
    v2 = parse_verdict('Here you go:\n```json\n{"verdict": "mostly true", "confidence": "HIGH", "summary": "ok"}\n```')
    assert v2.verdict == "TRUE" and v2.confidence == "high"


def test_parse_verdict_rejects_unknown():
    with pytest.raises(ValueError):
        parse_verdict('{"verdict":"PANTS ON FIRE"}')
    with pytest.raises(ValueError):
        parse_verdict("no json here")


def test_extract_grounding_filters_dedupes_and_ranks():
    resp = grounded_response(
        "{}",
        [("youtube.com", ""), ("reuters.com", ""), ("who.int", ""), ("reuters.com", ""), ("randomblog.net", ""), ("www.facebook.com", "")],
    )
    g = extract_grounding(resp)
    domains = [s["domain"] for s in g["sources"]]
    assert domains == ["who.int", "reuters.com", "randomblog.net"]
    assert g["dropped"] == 2
    assert g["sources"][0]["kind"] == "official"
    assert g["queries"] == ["q1"]
    assert "chips" in g["suggestions_html"]


def test_extract_grounding_handles_missing_metadata():
    resp = types.GenerateContentResponse.model_validate({"candidates": [{"content": {"parts": [{"text": "x"}]}}]})
    assert extract_grounding(resp) == {"sources": [], "queries": [], "suggestions_html": None, "dropped": 0}


def test_no_source_no_verdict_rule():
    verdict = VerdictResult(verdict="FALSE", confidence="high", summary="It is false.")
    result = apply_rules(verdict, {"sources": []})
    assert result["verdict"] == "UNVERIFIABLE"
    assert result["model_verdict"] == "FALSE"
    assert result["rule"] == "no_sources"
    kept = apply_rules(verdict, {"sources": [{"domain": "who.int"}]})
    assert kept["verdict"] == "FALSE" and kept["rule"] is None


def test_safe_entry_point_strips_scripts_and_handlers():
    html = '<div onclick="steal()">a</div><script>alert(1)</script><a href="x" onmouseover=\'bad()\'>b</a>'
    out = safe_entry_point(html)
    assert "script" not in out and "onclick" not in out and "onmouseover" not in out
    assert '<a href="x">b</a>' in out


def test_source_classification():
    assert normalize_domain("https://www.WHO.int/news/x") == "who.int"
    assert classify("mohfw.gov.in") == "official"
    assert classify("pubmed.ncbi.nlm.nih.gov") == "official"  # .gov suffix wins
    assert classify("thelancet.com") == "research"
    assert classify("iitb.ac.in") == "research"
    assert classify("boomlive.in") == "factcheck"
    assert classify("thehindu.com") == "news"
    assert classify("en.wikipedia.org") == "reference"
    assert classify("someblog.net") == "other"
    assert is_excluded("m.youtube.com") and is_excluded("x.com") and not is_excluded("box.com")


def test_score_weights_and_labels():
    claims = [
        {"verdict": "TRUE", "importance": "high"},
        {"verdict": "FALSE", "importance": "low"},
        {"verdict": "UNVERIFIABLE", "importance": "high"},
    ]
    s = score_claims(claims)
    assert s["value"] == 75  # 3*1 / (3+1)
    assert s["scored"] == 2 and s["total"] == 3
    assert s["label"] == "Mixed accuracy"
    assert score_claims([{"verdict": "UNVERIFIABLE", "importance": "high"}])["value"] is None
    assert score_claims([{"verdict": "TRUE", "importance": "low"}])["label"] == "Mostly accurate"


def test_score_speakers_skips_silent_speakers():
    claims = [{"speaker": "S1", "verdict": "TRUE", "importance": "medium"}, {"speaker": "S1", "verdict": "FALSE", "importance": "medium"}]
    out = score_speakers(claims, [{"id": "S1", "label": "Host"}, {"id": "S2", "label": "Guest"}])
    assert len(out) == 1 and out[0]["score"] == 50 and out[0]["claims"] == 2


def test_verdict_json_contract_is_documented_in_prompt():
    from app.verify import SYSTEM_PROMPT

    text = SYSTEM_PROMPT.format(today="2026-10-16", language="Hindi")
    assert "Hindi" in text and "UNVERIFIABLE" in text
    json.loads('{"verdict": "TRUE", "confidence": "high", "summary": "", "correction": "", "explanation": ""}')

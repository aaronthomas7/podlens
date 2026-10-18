"""HTTP API in mock mode: streaming, caching, share links and input errors."""

import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
URL = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"


def events_of(resp):
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def test_health_and_config():
    assert client.get("/healthz").json()["backend"] == "mock"
    cfg = client.get("/api/config").json()
    assert cfg["mock"] is True and "Malayalam" in cfg["languages"]


def test_analyze_stream_then_cache_then_share():
    r = client.post("/api/analyze", json={"url": URL, "language": "Hindi", "duration": 300})
    assert r.status_code == 200
    evs = events_of(r)
    kinds = [e["type"] for e in evs if e["type"] != "ping"]
    assert kinds[0] == "status" and "meta" in kinds and "claims" in kinds and kinds[-1] == "done"
    analysis = evs[-1]["analysis"]
    assert analysis["language"] == "Hindi" and analysis["mock"] is True
    assert len([k for k in kinds if k == "verdict"]) == len(analysis["claims"])

    again = events_of(client.post("/api/analyze", json={"url": URL, "language": "Hindi", "duration": 300}))
    assert len(again) == 1 and again[0]["cached"] is True and again[0]["analysis"]["id"] == analysis["id"]

    shared = client.get(f"/api/analysis/{analysis['id']}")
    assert shared.status_code == 200 and shared.json()["id"] == analysis["id"]
    stream = events_of(client.get(f"/api/stream/{analysis['id']}"))
    assert stream[-1]["type"] == "done"
    assert client.get(f"/a/{analysis['id']}").status_code == 200

    recent = client.get("/api/recent").json()
    assert any(item["id"] == analysis["id"] for item in recent)


def test_input_errors():
    r = client.post("/api/analyze", json={"url": "https://vimeo.com/1"})
    assert r.status_code == 400 and "YouTube" in r.json()["error"]
    r = client.post("/api/analyze", json={"url": URL, "start": "5:00", "end": "1:00"})
    assert r.status_code == 400
    r = client.post("/api/analyze", json={"url": URL, "start": "soon"})
    assert r.status_code == 400
    assert client.get("/api/analysis/doesnotexist1").status_code == 404
    assert client.get("/api/analysis/../etc").status_code == 404

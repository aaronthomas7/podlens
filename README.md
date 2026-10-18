# PodLens

**Fact-check any YouTube video or podcast, claim by claim, at the second it was said.**

Paste a YouTube link. Gemini watches the video (audio, speakers and on-screen text) and lists every factual claim with its timestamp. Each claim is then checked against Google Search, and you get a verdict with the sources behind it: True, Misleading, False, Outdated, or Couldn't verify. Claims appear as colour-coded marks on a timeline under the video; tap one to jump to that moment.

Built by **Team Dronger** for the Google Cloud AI Builder Cup 2026, theme **Media, Content & Digital Experiences**.

## Why

Long-form YouTube podcasts are now a main source of health and money advice for millions of people, often in Hindi, Malayalam, Tamil and other languages that fact-checkers rarely cover. A false claim at minute 47 of a two-hour show is effectively invisible. PodLens makes every checkable claim visible, sourced and linkable.

## How it works

```
YouTube link
   │
   ▼
1. Watch     Gemini (video understanding) reads the YouTube video directly:
             speech in any language + on-screen text and charts.
             → structured JSON: claims, timestamps, speakers, quotes, translations
             (opinions, jokes and personal stories are skipped)
   │
   ▼
2. Check     One Gemini call per claim with Grounding with Google Search,
             run in parallel. Social media and YouTube are dropped as evidence.
             → verdict, confidence, correction, explanation, grounded sources
   │
   ▼
3. Guard     Plain code, not the model:
             • no grounded source → no verdict ("Couldn't verify", not scored)
             • sources classified Official / Research / Fact-checker / News / Web
             • trust score = weighted arithmetic over verdicts, fully explained
   │
   ▼
4. Show      Streamed live to the page; saved to Firestore so share links
             and repeat checks are instant.
```

Design choices that matter:

- **Two isolated stages.** The video is only seen by the extractor; the checker only sees one claim at a time and is told the text is untrusted. A video that says "ignore your instructions" can't steer its own verdicts.
- **No source, no verdict.** If Google Search grounding returns no usable source, the claim is shown as "Couldn't verify" and left out of the score, even if the model had an opinion.
- **Outdated is its own verdict.** "Pluto is the ninth planet" was true once; calling it simply false would be unfair to old videos.
- **Long videos.** Videos up to 30 minutes are read in full. Longer ones use Gemini's agentic video understanding (the model navigates the timeline itself) or a time range you choose.
- **Results in your language.** Verdicts can be written in English, Hindi, Malayalam, Tamil, Telugu, Kannada, Bengali, Marathi, Bahasa Indonesia, Japanese, Korean or Chinese.

## Google Cloud

| Piece | Used for |
| --- | --- |
| Gemini on Vertex AI | Video understanding of YouTube URLs, structured output, verification |
| Grounding with Google Search | Evidence for every verdict, plus the required Search Suggestions |
| Cloud Run | The web app and API (FastAPI, streaming responses) |
| Firestore | Finished fact-checks, share links, recent checks |
| Cloud Build + Artifact Registry | Source deploys |

## Run it locally

```bash
pip install -r requirements.txt

# No Google Cloud needed: labelled sample data
MOCK_MODE=1 uvicorn app.main:app --reload

# Real checks with a Gemini API key
GEMINI_API_KEY=your-key uvicorn app.main:app --reload

# Real checks with Vertex AI (after `gcloud auth application-default login`)
GOOGLE_CLOUD_PROJECT=your-project uvicorn app.main:app --reload
```

Open http://localhost:8000.

## Deploy to Cloud Run

In [Cloud Shell](https://shell.cloud.google.com), with billing enabled on the project:

```bash
git clone https://github.com/aaronthomas7/podlens.git && cd podlens
gcloud config set project YOUR_PROJECT_ID
bash deploy.sh
```

The script enables the APIs, creates a service account with the Vertex AI User and Firestore User roles, creates the Firestore database, and deploys. It prints the live URL at the end.

## Configuration

| Variable | Default | What it does |
| --- | --- | --- |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Model for both stages; falls back down the list if unavailable |
| `GEMINI_FALLBACK_MODELS` | 3.8 Flash, 3.6 Flash, 3.5 Flash, 3.5 Flash-Lite, 2.5 Flash | Tried in order on "model not found" |
| `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` | – / `global` | Vertex AI settings |
| `GEMINI_API_KEY` | – | Use the Gemini API instead of Vertex AI |
| `USE_FIRESTORE` | off | Persist results |
| `MAX_CLAIMS` | 12 | Claims checked per video |
| `MAX_WINDOW_SECONDS` | 1800 | Longest stretch read in one pass |
| `VERIFY_CONCURRENCY` | 4 | Parallel checks |
| `RATE_PER_IP_HOUR` / `RATE_GLOBAL_DAY` | 6 / 60 | Limits on new checks (cached results are free) |
| `YOUTUBE_API_KEY` | – | Adds publish date and duration |
| `MOCK_MODE` | off | Sample data, no Google Cloud calls |

## Tests

```bash
pip install pytest
python -m pytest -q
```

The suite runs the real pipeline against a fake Gemini transport built from SDK response types, checks request serialization for both Vertex AI and the Gemini API, and exercises the HTTP API in mock mode.

## Limits

- Only public YouTube videos (Gemini can't open private or unlisted ones).
- PodLens checks what is said, not whether the footage itself is edited or AI-generated.
- Verdicts can be wrong. Every one links to its sources so people can check for themselves.

## Project layout

```
app/
  main.py       FastAPI routes, streaming
  pipeline.py   runs a check end to end, emits progress events
  extract.py    stage 1: video → claims (Gemini video understanding)
  verify.py     stage 2: claim → verdict (Google Search grounding) + guardrails
  scoring.py    trust score
  sources.py    evidence classification
  store.py      memory + Firestore
  jobs.py       shared in-flight checks with event replay
static/         single-page frontend (no build step)
tests/
```

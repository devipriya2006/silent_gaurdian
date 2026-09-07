# 🛡️ Silent Guardian — Multimodal Emergency Detection System

A computer-vision / audio-analysis system that analyzes **video, audio,
and images** for observable indicators of potential physical
aggression or distress, captures evidence, and logs incidents to a
dashboard for human review.

> **Framing note (important for reports/viva):** every score this
> system produces is a *model confidence/risk indicator*, not proof
> that violence, abuse, or harassment occurred. Every HIGH/CRITICAL
> result is explicitly routed to human review rather than acted on
> automatically. See `detector/scoring.py` for the disclaimer text
> surfaced throughout the app.

## Features

- 🎥 **Video Analysis** — upload a clip or run a live webcam demo;
  motion-pattern analysis with a real-time score timeline
- 🎙️ **Audio Analysis** — upload a WAV file or record from the
  microphone (recorded client-side and encoded to WAV in-browser, so
  the server needs no ffmpeg/codec dependency)
- 🖼️ **Image Analysis** — upload a single photo for a lightweight
  visual-indicator check, explicitly framed as the weakest signal of
  the three
- 🧮 **Unified 0–100 scoring** — every mode reports through the same
  `detector/scoring.py` classifier: **LOW (0–29) / MODERATE (30–49) /
  HIGH (50–74) / CRITICAL (75–100)**
- 🚨 **Tiered alerts** — LOW: nothing · MODERATE: in-app warning only ·
  HIGH: strong in-app warning + saved for review · CRITICAL: prominent
  alert + external notification (email/webhook) if configured
- 🧠 **Duplicate-alert suppression** — a continuous high-score stretch
  (video) is treated as one event, not one incident per frame
- 🗂️ **Multimodal incident dashboard** — filter by source, classification,
  status, and date; confirm (Verified) or dismiss (False Alarm) each
  incident
- 📤 **CSV export** of the full incident log
- ☁️ **One-click Render deployment** via `render.yaml`

## Architecture

```
                    ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
                    │   Video     │   │   Audio     │   │   Image     │
                    │  (upload /  │   │ (upload /   │   │  (upload)   │
                    │   webcam)   │   │    mic)     │   │             │
                    └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
                           │                  │                 │
                    optical flow        energy/pitch      edge/contrast/
                    motion features      features         texture features
                           │                  │                 │
                           └────────┬─────────┴────────┬────────┘
                                    ▼                   
                       detector/scoring.py (0-100, LOW/MODERATE/HIGH/CRITICAL)
                                    │
                          score >= HIGH threshold?
                             │yes           │no
                             ▼               ▼
                  Evidence capture +   keep monitoring
                  Incident DB (SQLite) +
                  Tiered alert dispatch
                             │
                             ▼
                  Multimodal Review Dashboard
                  (filter, Verify / False Alarm)
```

### Detection approach per mode

All three detectors are deliberately transparent, dependency-light
pipelines rather than bundled black-box models — this makes them
runnable anywhere (no GPU, no large model download) and fully
explainable in a project report.

**Video** (`detector/violence_detector.py`) — dense optical flow
(Farneback) between consecutive frames reduced to motion energy,
spikiness, and directional chaos, adaptively normalized to the scene's
own baseline and smoothed over a sliding window.

**Audio** (`detector/audio_detector.py`) — RMS energy, energy-spike
ratio against the clip's own baseline, zero-crossing rate, and a
coarse FFT-based high-frequency energy ratio, combined into a score.
Built on the Python standard library `wave` module + NumPy only (no
librosa/ffmpeg), so it stays light for free-tier hosting.

**Image** (`detector/image_detector.py`) — edge density (Canny),
global contrast, and texture complexity (Laplacian variance). This
mode's output is deliberately capped well below 100, since a single
still image is the weakest of the three signals — there's no motion or
temporal pattern to analyze, only static texture statistics.

### Extending to trained deep models (suggested future work)

Each detector module exposes a small, swappable interface. To upgrade
accuracy:
- **Video** → train a 3D-CNN or ST-GCN on RWF-2000 / Hockey Fight and
  wrap it with the same `.extract()` / `.update()` interface as
  `MotionFeatureExtractor` / `ViolenceScorer`.
- **Audio** → train a small audio-event classifier (e.g. on a
  scream/shout dataset) and have it emit the same `{score, category}`
  shape as `analyze_audio_bytes()`.
- **Image** → fine-tune an image classifier on an action/pose dataset
  and swap in for `analyze_image_bgr()`.

Because `app.py` only depends on each module's function signature —
not on the specific technique — none of the alerting, storage, or
dashboard code needs to change.

## Local setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Visit `http://localhost:5000`.

## Deploying on Render

**Option A — Blueprint (recommended):**
1. Push this project to a GitHub repo, with `app.py` and
   `requirements.txt` at the **repo root** (or set Root Directory in
   Render's settings if they're in a subfolder).
2. Render → **New → Blueprint** → select the repo. It reads
   `render.yaml` and provisions the service automatically.

**Option B — Manual web service:**
1. **New → Web Service**, connect your repo.
2. Build command: `pip install -r requirements.txt`
3. Start command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
4. Add environment variables as needed (see `.env.example`).

`runtime.txt` pins Python to 3.11 for stable OpenCV/NumPy wheel
availability — recommended to keep as-is unless you've verified newer
versions work.

> **Ephemeral disk note:** Render's free tier disk resets on
> redeploy/restart — the SQLite incident DB and saved evidence files
> won't persist between sessions unless you attach a paid Render Disk
> or move to managed Postgres + object storage.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | Flask session signing key | dev key (change in prod) |
| `ALERT_COOLDOWN_SECONDS` | Minimum gap between live-webcam alerts per session | `15` |
| `FRAME_SAMPLE_RATE` | Analyze every Nth frame of uploaded videos | `10` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `ALERT_EMAIL_TO` | Email alerts (CRITICAL only) | unset (logging only) |
| `ALERT_WEBHOOK_URL` | Slack/Discord-style webhook alerts (CRITICAL only) | unset (logging only) |

## Project structure

```
silent_guardian/
├── app.py                       # Flask app & routes (video/audio/image/dashboard)
├── detector/
│   ├── scoring.py               # Unified 0-100 → LOW/MODERATE/HIGH/CRITICAL
│   ├── violence_detector.py     # Video: motion extraction + scoring
│   ├── audio_detector.py        # Audio: energy/pitch feature scoring
│   └── image_detector.py        # Image: texture/edge heuristic scoring
├── utils/
│   ├── database.py              # SQLite incident storage + filtering
│   └── alerts.py                # Tiered alert dispatch (email/webhook)
├── templates/                   # index (landing), video, audio, image, dashboard
├── static/                      # CSS + per-page JS
├── data/evidence/                # Saved evidence files (gitignored)
├── requirements.txt
├── runtime.txt                  # Pins Python 3.11 for Render
├── Procfile
└── render.yaml
```

## Report-ready talking points

- **Problem**: manual monitoring across video, audio, and image
  evidence doesn't scale, and incidents are often noticed too late or
  from only one modality.
- **Approach**: three independent, explainable detectors report
  through one unified 0–100 risk scale, so results are comparable and
  consistently framed across modalities — always as indicators for
  human review, never as automated proof.
- **System design**: modular pipeline (extraction → scoring → tiered
  alert → storage → filterable review dashboard), deployable as a
  lightweight web service with no GPU or large model dependency.
- **Evaluation ideas**: benchmark the video detector against RWF-2000 /
  Hockey Fight, the audio detector against a distress/scream dataset,
  by treating each score + threshold as a binary classifier and
  reporting precision/recall/F1 and false-alarm rate.
- **Future scope**: swap each heuristic detector for a trained deep
  model behind the same interface; add multi-camera support; person
  re-identification; mobile push notifications.

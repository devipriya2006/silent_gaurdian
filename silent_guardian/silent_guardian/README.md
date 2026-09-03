# 🛡️ Silent Guardian — AI-Based Violence Detection and Smart Alert System

A computer-vision system that analyzes video (uploaded clips or a live
webcam feed) to detect potential physical violence, automatically
captures evidence frames, raises alerts, and logs incidents to a
dashboard for human review.

## Features

- 📼 **Upload & analyze** any video file, with a full violence-score
  timeline chart
- 🎥 **Live camera demo** running in-browser, streaming frames to the
  backend for real-time scoring
- 🧠 **Adaptive motion-analysis detection engine** (optical flow based)
  that calibrates to each scene's normal activity level instead of
  using a fixed threshold
- 🚨 **Automatic evidence capture** — snapshot saved the moment an
  incident is flagged
- 📧 **Configurable alerting** — email (SMTP) and/or webhook
  (Slack/Discord-style), with a cooldown to prevent alert spam
- 🗂️ **Incident dashboard** — review, confirm, or dismiss (false
  positive) every flagged incident, with severity levels and stats
- 📤 **CSV export** of the full incident log
- ☁️ **One-click Render deployment** via `render.yaml`

## Architecture

```
Browser (upload or webcam) ──▶ Flask API ──▶ Motion Feature Extractor
                                                  │ (optical flow)
                                                  ▼
                                          Violence Scorer
                                        (adaptive + smoothed)
                                                  │
                                     threshold crossed?
                                       │yes              │no
                                       ▼                  ▼
                          Evidence capture +        keep streaming
                          Incident DB (SQLite) +
                          Alert dispatch (email/webhook)
                                       │
                                       ▼
                              Review Dashboard (Flask templates)
```

### Detection approach

The core detector (`detector/violence_detector.py`) is deliberately
built as a transparent, dependency-light pipeline rather than a
bundled black-box model, so it:

- runs anywhere (no GPU, no multi-hundred-MB model download)
- is fully explainable in a project report/viva
- gives you concrete, defensible things to say about *why* a frame was
  flagged (motion energy, spikiness, directional chaos)

**Pipeline:**
1. **Dense optical flow** (Farneback) between consecutive frames
   estimates per-pixel motion vectors.
2. Motion vectors are reduced to four interpretable features:
   `motion_energy`, `motion_std`, `high_motion_ratio`,
   `direction_entropy` (how many different directions the fastest
   pixels are moving in — a struggle/shove moves limbs in many
   directions at once; walking or panning does not).
3. Each scene keeps a **rolling baseline** of its own recent motion
   energy, so the detector adapts instead of using one fixed
   sensitivity for every camera/scene.
4. Scores are **smoothed over a sliding window** so a single noisy
   frame can't fire a false alert.

### Extending to a trained deep model (suggested future work)

For a stronger classifier, train a 3D-CNN or ST-GCN on a public
violence-detection dataset such as **RWF-2000** or **Hockey Fight**,
then wrap it in a class exposing the same `.extract()` / `.update()`
interface as `MotionFeatureExtractor` / `ViolenceScorer`. Because
`app.py` only depends on that interface — not on optical flow
specifically — you can swap detectors without touching alerts,
storage, or the dashboard. This is a good "Future Scope" section for
your report.

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
1. Push this project to a GitHub repo.
2. In Render, choose **New → Blueprint**, point it at your repo. Render
   will read `render.yaml` and provision everything automatically.

**Option B — Manual web service:**
1. **New → Web Service**, connect your repo.
2. Build command: `pip install -r requirements.txt`
3. Start command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
4. Add environment variables as needed (see `.env.example`).

> Note: Render's free-tier disk is ephemeral — evidence images and the
> SQLite DB will reset on redeploy/restart. For a persistent demo,
> attach a Render Disk, or swap `IncidentDB` for a managed Postgres
> instance (the interface in `utils/database.py` is small and easy to
> port).

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | Flask session signing key | dev key (change in prod) |
| `VIOLENCE_THRESHOLD` | Smoothed score above which an incident fires | `0.55` |
| `ALERT_COOLDOWN_SECONDS` | Minimum gap between alerts per session | `15` |
| `FRAME_SAMPLE_RATE` | Analyze every Nth frame of uploaded videos | `5` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `ALERT_EMAIL_TO` | Email alerts | unset (logging only) |
| `ALERT_WEBHOOK_URL` | Slack/Discord-style webhook alerts | unset (logging only) |

## Project structure

```
silent_guardian/
├── app.py                       # Flask app & routes
├── detector/
│   └── violence_detector.py     # Motion extraction + scoring engine
├── utils/
│   ├── database.py              # SQLite incident storage
│   └── alerts.py                # Email/webhook alert dispatch
├── templates/                   # index.html, dashboard.html, base.html
├── static/                      # CSS + JS
├── data/evidence/                # Saved evidence frames (gitignored)
├── requirements.txt
├── Procfile
└── render.yaml
```

## Report-ready talking points

- **Problem**: manual CCTV monitoring doesn't scale; incidents are
  often noticed too late.
- **Approach**: real-time motion-pattern analysis flags abnormal,
  high-energy, multi-directional motion characteristic of physical
  altercations, adapting per-scene rather than using one global
  threshold.
- **System design**: modular pipeline (extraction → scoring → alert →
  storage → review UI), deployable as a lightweight web service.
- **Evaluation ideas**: benchmark against RWF-2000 / Hockey Fight
  datasets by treating the smoothed score + threshold as a binary
  classifier, and report precision/recall/F1 and false-alarm rate.
- **Future scope**: swap in a trained deep model, add multi-camera
  support, person re-identification, and mobile push notifications.

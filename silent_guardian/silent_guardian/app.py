"""
Silent Guardian — AI-Based Violence Detection and Smart Alert System
=====================================================================

Flask backend that:
  1. Accepts an uploaded video (or a live webcam stream from the browser)
  2. Runs it through a motion-analysis based violence-detection pipeline
  3. Raises an alert + stores evidence frames when violence is detected
  4. Exposes a dashboard for human review of flagged incidents

Run locally:
    pip install -r requirements.txt
    python app.py

Deploy on Render:
    See render.yaml / README.md
"""

import base64
import csv
import io
import os
import time
import uuid
from datetime import datetime

import cv2
import numpy as np
from flask import (
    Flask, render_template, request, jsonify,
    send_from_directory, Response, session
)

from detector.violence_detector import MotionFeatureExtractor, ViolenceScorer
from utils.database import IncidentDB
from utils.alerts import send_alert

# --------------------------------------------------------------------------
# App setup
# --------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "silent-guardian-dev-secret")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EVIDENCE_DIR = os.path.join(BASE_DIR, "data", "evidence")
DB_PATH = os.path.join(BASE_DIR, "instance", "incidents.db")
os.makedirs(EVIDENCE_DIR, exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

db = IncidentDB(DB_PATH)

# Tunables (overridable via environment variables so they can be changed
# per-deployment without touching code)
VIOLENCE_THRESHOLD = float(os.environ.get("VIOLENCE_THRESHOLD", 0.55))
ALERT_COOLDOWN_SECONDS = int(os.environ.get("ALERT_COOLDOWN_SECONDS", 15))
FRAME_SAMPLE_RATE = int(os.environ.get("FRAME_SAMPLE_RATE", 5))  # analyze every Nth frame

# In-memory per-session detector state for the live webcam demo.
# (Fine for a single-instance mini-project deployment; a production
# system would move this to Redis or similar.)
_live_sessions = {}
_last_alert_time = {}


def _get_session_id():
    if "sid" not in session:
        session["sid"] = str(uuid.uuid4())
    return session["sid"]


def _get_live_detector(sid):
    if sid not in _live_sessions:
        _live_sessions[sid] = {
            "extractor": MotionFeatureExtractor(),
            "scorer": ViolenceScorer(threshold=VIOLENCE_THRESHOLD),
        }
    return _live_sessions[sid]


def _severity_label(score):
    if score >= 0.8:
        return "High"
    if score >= VIOLENCE_THRESHOLD:
        return "Medium"
    return "Low"


def _maybe_alert(sid, score, frame_bgr, source_label):
    """Fire an alert + persist an incident if cooldown has elapsed."""
    now = time.time()
    last = _last_alert_time.get(sid, 0)
    if now - last < ALERT_COOLDOWN_SECONDS:
        return None

    _last_alert_time[sid] = now

    filename = f"incident_{uuid.uuid4().hex[:10]}.jpg"
    filepath = os.path.join(EVIDENCE_DIR, filename)
    cv2.imwrite(filepath, frame_bgr)

    incident = db.add_incident(
        timestamp=datetime.utcnow().isoformat(),
        confidence=round(score, 3),
        severity=_severity_label(score),
        evidence_file=filename,
        source=source_label,
    )

    send_alert(
        subject="Silent Guardian: Potential violence detected",
        message=(
            f"Incident #{incident['id']}\n"
            f"Source: {source_label}\n"
            f"Confidence: {score:.2f}\n"
            f"Severity: {_severity_label(score)}\n"
            f"Time (UTC): {incident['timestamp']}"
        ),
        image_path=filepath,
    )
    return incident


# --------------------------------------------------------------------------
# Page routes
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", threshold=VIOLENCE_THRESHOLD)


@app.route("/dashboard")
def dashboard():
    incidents = db.list_incidents()
    stats = db.get_stats()
    return render_template("dashboard.html", incidents=incidents, stats=stats)


@app.route("/evidence/<path:filename>")
def evidence(filename):
    return send_from_directory(EVIDENCE_DIR, filename)


# --------------------------------------------------------------------------
# API: video file upload analysis
# --------------------------------------------------------------------------
@app.route("/api/analyze_video", methods=["POST"])
def analyze_video():
    if "video" not in request.files:
        return jsonify({"error": "No video file provided"}), 400

    file = request.files["video"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    tmp_path = os.path.join(BASE_DIR, "data", f"upload_{uuid.uuid4().hex[:8]}.mp4")
    file.save(tmp_path)

    cap = cv2.VideoCapture(tmp_path)
    if not cap.isOpened():
        os.remove(tmp_path)
        return jsonify({"error": "Could not read video file"}), 400

    extractor = MotionFeatureExtractor()
    scorer = ViolenceScorer(threshold=VIOLENCE_THRESHOLD)

    timeline = []
    incidents_raised = []
    frame_idx = 0
    sid = f"upload-{uuid.uuid4().hex[:6]}"
    fps = cap.get(cv2.CAP_PROP_FPS) or 25

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1

        if frame_idx % FRAME_SAMPLE_RATE != 0:
            continue

        features = extractor.extract(frame)
        score = scorer.update(features)
        t_sec = round(frame_idx / fps, 2)
        timeline.append({"t": t_sec, "score": round(score, 3)})

        if scorer.is_violent(score):
            incident = _maybe_alert(sid, score, frame, source_label=f"upload:{file.filename}")
            if incident:
                incidents_raised.append({**incident, "t": t_sec})

    cap.release()
    os.remove(tmp_path)

    return jsonify({
        "timeline": timeline,
        "incidents": incidents_raised,
        "max_score": max([p["score"] for p in timeline], default=0),
        "frames_analyzed": len(timeline),
    })


# --------------------------------------------------------------------------
# API: live webcam frame-by-frame analysis
# --------------------------------------------------------------------------
@app.route("/api/analyze_frame", methods=["POST"])
def analyze_frame():
    data = request.get_json(silent=True) or {}
    image_b64 = data.get("image")
    if not image_b64:
        return jsonify({"error": "No image provided"}), 400

    try:
        header, encoded = image_b64.split(",", 1) if "," in image_b64 else (None, image_b64)
        img_bytes = base64.b64decode(encoded)
        np_arr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    except Exception:
        return jsonify({"error": "Invalid image data"}), 400

    if frame is None:
        return jsonify({"error": "Could not decode image"}), 400

    sid = _get_session_id()
    state = _get_live_detector(sid)
    features = state["extractor"].extract(frame)
    score = state["scorer"].update(features)
    violent = state["scorer"].is_violent(score)

    incident = None
    if violent:
        incident = _maybe_alert(sid, score, frame, source_label="live-webcam")

    return jsonify({
        "score": round(score, 3),
        "violent": violent,
        "severity": _severity_label(score),
        "incident": incident,
    })


@app.route("/api/reset_live", methods=["POST"])
def reset_live():
    sid = _get_session_id()
    _live_sessions.pop(sid, None)
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# API: incidents management
# --------------------------------------------------------------------------
@app.route("/api/incidents", methods=["GET"])
def api_incidents():
    return jsonify(db.list_incidents())


@app.route("/api/incidents/<int:incident_id>/review", methods=["POST"])
def review_incident(incident_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status", "reviewed")  # reviewed | false_positive | confirmed
    db.update_status(incident_id, status)
    return jsonify({"ok": True})


@app.route("/api/incidents/export")
def export_incidents():
    incidents = db.list_incidents()
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["id", "timestamp", "confidence", "severity", "source", "status", "evidence_file"],
    )
    writer.writeheader()
    for row in incidents:
        writer.writerow({k: row.get(k) for k in writer.fieldnames})

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=incidents_report.csv"},
    )


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

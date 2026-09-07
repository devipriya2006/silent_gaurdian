"""
Silent Guardian — Multimodal Emergency Detection System
=========================================================

Flask backend covering three independent detection modes:

  1. VIDEO  — uploaded clip or live webcam, motion-analysis based
  2. AUDIO  — uploaded file or browser microphone recording, acoustic
              energy/pitch-pattern based
  3. IMAGE  — single uploaded photo, visual-texture heuristic based

All three report a normalized 0-100 "risk/confidence indicator" and a
LOW / MODERATE / HIGH / CRITICAL classification via one shared scoring
module (detector/scoring.py), and route HIGH/CRITICAL results into a
common incident dashboard for human review.

IMPORTANT: none of these scores are proof that violence, abuse, or a
crime occurred. Every flagged result is explicitly framed as an
indicator for human review — see detector/scoring.py disclaimers,
which are surfaced in every relevant API response and template.

Run locally:
    pip install -r requirements.txt
    python app.py

Deploy on Render: see render.yaml / README.md
"""

import base64
import csv
import io
import os
import time
import uuid
from datetime import datetime, timezone

import cv2
import numpy as np
from flask import (
    Flask, render_template, request, jsonify,
    send_from_directory, Response, session
)
from werkzeug.exceptions import HTTPException

from detector.violence_detector import MotionFeatureExtractor, ViolenceScorer
from detector import scoring
from detector.audio_detector import analyze_audio_bytes
from detector.image_detector import analyze_image_bgr
from utils.database import IncidentDB, VALID_STATUSES
from utils.alerts import dispatch as dispatch_alert

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

# Tunables (overridable via environment variables)
ALERT_COOLDOWN_SECONDS = int(os.environ.get("ALERT_COOLDOWN_SECONDS", 15))
FRAME_SAMPLE_RATE = int(os.environ.get("FRAME_SAMPLE_RATE", 10))
HIGH_THRESHOLD = 50   # score at/above this can create an incident
MODERATE_THRESHOLD = 30
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
ALLOWED_VIDEO_EXTENSIONS = {"mp4", "webm", "avi", "mov", "mkv"}
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

# In-memory per-session state for the live webcam / video-event dedup.
# Fine for a single-instance mini-project deployment; a production
# system would move this to Redis or similar.
_live_sessions = {}
_last_alert_time = {}
_active_event = {}  # sid -> bool, tracks "are we still inside the same event"


def _get_session_id():
    if "sid" not in session:
        session["sid"] = str(uuid.uuid4())
    return session["sid"]


def _get_live_detector(sid):
    if sid not in _live_sessions:
        _live_sessions[sid] = {
            "extractor": MotionFeatureExtractor(),
            "scorer": ViolenceScorer(threshold=HIGH_THRESHOLD / 100.0),
        }
    return _live_sessions[sid]


def _cooldown_ok(sid):
    now = time.time()
    last = _last_alert_time.get(sid, 0)
    if now - last < ALERT_COOLDOWN_SECONDS:
        return False
    _last_alert_time[sid] = now
    return True


def _save_evidence_frame(frame_bgr):
    filename = f"incident_{uuid.uuid4().hex[:10]}.jpg"
    filepath = os.path.join(EVIDENCE_DIR, filename)
    cv2.imwrite(filepath, frame_bgr)
    return filename, filepath


def _save_evidence_bytes(raw_bytes, ext="jpg"):
    filename = f"incident_{uuid.uuid4().hex[:10]}.{ext}"
    filepath = os.path.join(EVIDENCE_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(raw_bytes)
    return filename, filepath


def _raise_incident(source, score, level, evidence_file=None, evidence_path=None, detail=None):
    """
    Creates an incident (if reportable), dispatches a tiered alert, and
    returns (incident_or_None, alert_result).
    """
    if not scoring.is_reportable(level):
        return None, {"tier": "none", "external_sent": False}

    incident = db.add_incident(
        timestamp=datetime.now(timezone.utc).isoformat(),
        source=source,
        score=score,
        classification=level,
        evidence_file=evidence_file,
        detail=detail,
    )

    alert_result = dispatch_alert(
        level=level,
        subject=f"Silent Guardian: {level} indicator detected ({source})",
        message=(
            f"Incident #{incident['id']}\n"
            f"Source: {source}\n"
            f"Score: {score}/100\n"
            f"Classification: {level}\n"
            f"Time (UTC): {incident['timestamp']}\n\n"
            f"{scoring.DISCLAIMER}"
        ),
        image_path=evidence_path,
    )
    return incident, alert_result


def _severity_from_score(score_0_100):
    return scoring.classify(score_0_100)


def _record_analysis(source, classified):
    """Persist an audit entry for a completed detector run."""
    db.add_analysis(
        timestamp=datetime.now(timezone.utc).isoformat(),
        source=source,
        score=classified["score"],
        classification=classified["level"],
    )


def _extension(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _validate_upload(file, allowed_extensions, label):
    if not file or not file.filename:
        return f"Please choose a {label} file."
    if _extension(file.filename) not in allowed_extensions:
        return f"Unsupported {label} type. Please choose: {', '.join(sorted(allowed_extensions))}."
    if request.content_length and request.content_length > MAX_UPLOAD_BYTES:
        return f"The {label} exceeds the 100 MB upload limit."
    return None


# --------------------------------------------------------------------------
# Page routes
# --------------------------------------------------------------------------
@app.route("/")
def index():
    stats = db.get_stats()
    return render_template("index.html", stats=stats)


@app.route("/video")
def video_page():
    return render_template("video.html", high_threshold=HIGH_THRESHOLD)


@app.route("/audio")
def audio_page():
    return render_template("audio.html")


@app.route("/image")
def image_page():
    return render_template("image.html")


@app.route("/dashboard")
def dashboard():
    incidents = db.list_incidents()
    stats = db.get_stats()
    return render_template("dashboard.html", incidents=incidents, stats=stats,
                            valid_statuses=VALID_STATUSES)


@app.route("/evidence/<path:filename>")
def evidence(filename):
    return send_from_directory(EVIDENCE_DIR, filename)


# --------------------------------------------------------------------------
# API: VIDEO analysis
# --------------------------------------------------------------------------
@app.route("/api/analyze_video", methods=["POST"])
def analyze_video():
    file = request.files.get("video")
    error = _validate_upload(file, ALLOWED_VIDEO_EXTENSIONS, "video")
    if error:
        return jsonify({"error": error}), 400

    tmp_path = os.path.join(BASE_DIR, "data", f"upload_{uuid.uuid4().hex[:8]}.mp4")
    file.save(tmp_path)

    cap = cv2.VideoCapture(tmp_path)
    if not cap.isOpened():
        os.remove(tmp_path)
        return jsonify({"error": "Could not read video file"}), 400

    extractor = MotionFeatureExtractor()
    scorer = ViolenceScorer(threshold=HIGH_THRESHOLD / 100.0)

    timeline = []
    incidents_raised = []
    frame_idx = 0
    sid = f"upload-{uuid.uuid4().hex[:6]}"
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    event_active = False

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame_idx += 1

            if frame_idx % FRAME_SAMPLE_RATE != 0:
                continue

            features = extractor.extract(frame)
            raw_score = scorer.update(features)  # 0-1
            score_100 = round(raw_score * 100, 1)
            classified = _severity_from_score(score_100)
            t_sec = round(frame_idx / fps, 2)
            timeline.append({"t": t_sec, "score": score_100, "level": classified["level"]})

            if score_100 >= HIGH_THRESHOLD:
                if not event_active:
                    # One continuous high-score stretch is one event.
                    event_active = True
                    filename, filepath = _save_evidence_frame(frame)
                    incident, _ = _raise_incident(
                        source="video", score=score_100, level=classified["level"],
                        evidence_file=filename, evidence_path=filepath,
                        detail=f"t={t_sec}s of upload:{file.filename}",
                    )
                    if incident:
                        incidents_raised.append({**incident, "t": t_sec})
            else:
                event_active = False
    finally:
        cap.release()
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    peak_score = max([p["score"] for p in timeline], default=0)
    _record_analysis("video", scoring.classify(peak_score))

    return jsonify({
        "timeline": timeline,
        "incidents": incidents_raised,
        "max_score": peak_score,
        "frames_analyzed": len(timeline),
        "disclaimer": scoring.DISCLAIMER,
    })


@app.route("/api/analyze_frame", methods=["POST"])
def analyze_frame():
    """Live webcam: one frame per call."""
    data = request.get_json(silent=True) or {}
    image_b64 = data.get("image")
    if not image_b64:
        return jsonify({"error": "No image provided"}), 400

    try:
        encoded = image_b64.split(",", 1)[1] if "," in image_b64 else image_b64
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
    raw_score = state["scorer"].update(features)
    score_100 = round(raw_score * 100, 1)
    classified = _severity_from_score(score_100)
    _record_analysis("video", classified)

    incident = None
    was_active = _active_event.get(sid, False)

    if score_100 >= HIGH_THRESHOLD:
        if not was_active and _cooldown_ok(sid):
            filename, filepath = _save_evidence_frame(frame)
            incident, _ = _raise_incident(
                source="video", score=score_100, level=classified["level"],
                evidence_file=filename, evidence_path=filepath, detail="live-webcam",
            )
        _active_event[sid] = True
    else:
        _active_event[sid] = False

    return jsonify({
        "score": score_100,
        "level": classified["level"],
        "meaning": classified["meaning"],
        "incident": incident,
    })


@app.route("/api/reset_live", methods=["POST"])
def reset_live():
    sid = _get_session_id()
    _live_sessions.pop(sid, None)
    _active_event.pop(sid, None)
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# API: AUDIO analysis
# --------------------------------------------------------------------------
@app.route("/api/analyze_audio", methods=["POST"])
def analyze_audio():
    file = request.files.get("audio")
    error = _validate_upload(file, {"wav"}, "audio")
    if error:
        return jsonify({"error": error}), 400

    raw_bytes = file.read()

    try:
        result = analyze_audio_bytes(raw_bytes)
    except Exception as exc:
        return jsonify({
            "error": (
                "Could not analyze this audio. Please upload/record a WAV "
                f"file. ({exc})"
            )
        }), 400

    classified = scoring.classify(result["score"])
    _record_analysis("audio", classified)

    incident = None
    if classified["level"] in ("HIGH", "CRITICAL"):
        filename, filepath = _save_evidence_bytes(raw_bytes, ext="wav")
        incident, _ = _raise_incident(
            source="audio", score=result["score"], level=classified["level"],
            evidence_file=filename, evidence_path=None,
            detail=f"{result['category']} (peak @ {result['peak_time_sec']}s)",
        )

    return jsonify({
        "score": classified["score"],
        "level": classified["level"],
        "meaning": classified["meaning"],
        "category": result["category"],
        "duration_sec": result["duration_sec"],
        "peak_time_sec": result["peak_time_sec"],
        "stats": result["stats"],
        "incident": incident,
        "disclaimer": scoring.AUDIO_DISCLAIMER,
    })


# --------------------------------------------------------------------------
# API: IMAGE analysis
# --------------------------------------------------------------------------
@app.route("/api/analyze_image", methods=["POST"])
def analyze_image():
    file = request.files.get("image")
    error = _validate_upload(file, ALLOWED_IMAGE_EXTENSIONS, "image")
    if error:
        return jsonify({"error": error}), 400

    raw_bytes = file.read()
    np_arr = np.frombuffer(raw_bytes, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    if frame is None:
        return jsonify({"error": "Could not decode image. Please upload a JPG or PNG."}), 400

    result = analyze_image_bgr(frame)
    classified = scoring.classify(result["score"])
    _record_analysis("image", classified)

    incident = None
    if classified["level"] in ("HIGH", "CRITICAL"):
        ext = "png" if file.filename.lower().endswith(".png") else "jpg"
        filename, filepath = _save_evidence_bytes(raw_bytes, ext=ext)
        incident, _ = _raise_incident(
            source="image", score=result["score"], level=classified["level"],
            evidence_file=filename, evidence_path=filepath,
            detail=f"uploaded:{file.filename}",
        )

    return jsonify({
        "score": classified["score"],
        "level": classified["level"],
        "meaning": classified["meaning"],
        "stats": result["stats"],
        "incident": incident,
        "disclaimer": scoring.IMAGE_DISCLAIMER,
    })


# --------------------------------------------------------------------------
# API: incidents management
# --------------------------------------------------------------------------
@app.route("/api/incidents", methods=["GET"])
def api_incidents():
    incidents = db.list_incidents(
        source=request.args.get("source"),
        classification=request.args.get("classification"),
        status=request.args.get("status"),
        date_from=request.args.get("date_from"),
        date_to=request.args.get("date_to"),
    )
    return jsonify(incidents)


@app.route("/api/incidents/<int:incident_id>/review", methods=["POST"])
def review_incident(incident_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in VALID_STATUSES:
        return jsonify({"error": f"status must be one of {VALID_STATUSES}"}), 400
    db.update_status(incident_id, status)
    return jsonify({"ok": True})


@app.route("/api/incidents/export")
def export_incidents():
    incidents = db.list_incidents()
    buf = io.StringIO()
    fieldnames = ["id", "timestamp", "source", "score", "classification",
                  "status", "detail", "evidence_file"]
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in incidents:
        writer.writerow({k: row.get(k) for k in fieldnames})

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=incidents_report.csv"},
    )


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.errorhandler(Exception)
def handle_error(e):
    if isinstance(e, HTTPException):
        return jsonify({"error": e.description}), e.code
    import traceback
    traceback.print_exc()
    return jsonify({"error": "An unexpected server error occurred. Please try again."}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

"""
Tiered alert dispatch.

Alert behavior by classification level (per project spec):
  LOW       -> no alert at all
  MODERATE  -> shown as a warning in the results UI only (no external send)
  HIGH      -> shown as a strong warning in the UI, incident saved for
               review, but no external notification (keeps it a
               reviewer-facing signal, not a page-someone-at-2am signal)
  CRITICAL  -> prominent emergency alert in the UI AND an external
               notification (email/webhook), since this is the tier
               meant for urgent human attention

Email/webhook channels are both optional and configured purely via
environment variables. If neither is configured, CRITICAL alerts are
still logged to stdout and still create an incident — the rest of the
system works fully without any alerting credentials, which keeps the
project easy to demo.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage

import requests


def dispatch(level, subject, message, image_path=None):
    """
    Routes an alert according to its classification level.
    Returns a dict describing what happened, for the API response.
    """
    if level == "LOW":
        return {"tier": "none", "external_sent": False}

    if level == "MODERATE":
        _log(subject, message, tag="WARNING")
        return {"tier": "warning", "external_sent": False}

    if level == "HIGH":
        _log(subject, message, tag="STRONG WARNING")
        return {"tier": "strong_warning", "external_sent": False}

    # CRITICAL
    _log(subject, message, tag="EMERGENCY")
    sent = _send_external(subject, message, image_path)
    return {"tier": "emergency", "external_sent": sent}


def _log(subject, message, tag):
    print("=" * 60)
    print(f"[{tag}] {subject}")
    print(message)
    print("=" * 60)


def _send_external(subject, message, image_path=None):
    sent_any = False
    if _email_configured():
        try:
            _send_email(subject, message, image_path)
            sent_any = True
        except Exception as exc:  # pragma: no cover - best effort
            print(f"[alerts] Email send failed: {exc}")

    if os.environ.get("ALERT_WEBHOOK_URL"):
        try:
            _send_webhook(subject, message)
            sent_any = True
        except Exception as exc:  # pragma: no cover - best effort
            print(f"[alerts] Webhook send failed: {exc}")

    return sent_any


def _email_configured():
    return all([
        os.environ.get("SMTP_HOST"),
        os.environ.get("SMTP_USER"),
        os.environ.get("SMTP_PASSWORD"),
        os.environ.get("ALERT_EMAIL_TO"),
    ])


def _send_email(subject, message, image_path=None):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", 587))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    to_addr = os.environ["ALERT_EMAIL_TO"]
    from_addr = os.environ.get("ALERT_EMAIL_FROM", user)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(message)

    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as f:
            msg.add_attachment(
                f.read(), maintype="image", subtype="jpeg", filename="evidence.jpg"
            )

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port) as server:
        server.starttls(context=context)
        server.login(user, password)
        server.send_message(msg)


def _send_webhook(subject, message):
    url = os.environ["ALERT_WEBHOOK_URL"]
    payload = {"text": f"*{subject}*\n{message}"}
    requests.post(url, json=payload, timeout=5)

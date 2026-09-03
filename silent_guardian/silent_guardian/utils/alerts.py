"""
Alert dispatch utility.

Supports two optional notification channels, both configured purely
via environment variables so no secrets live in code:

  1. Email (SMTP) — set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
     ALERT_EMAIL_TO (recipient), ALERT_EMAIL_FROM (optional, defaults
     to SMTP_USER).

  2. Webhook (e.g. Slack/Discord incoming webhook, or any URL that
     accepts a JSON POST) — set ALERT_WEBHOOK_URL.

If none of these are configured, alerts are simply logged to stdout —
the rest of the system (evidence capture, DB logging, dashboard) still
works fully, which keeps the project easy to demo without setting up
email credentials.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage

import requests


def send_alert(subject, message, image_path=None):
    _log_alert(subject, message)

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


def _log_alert(subject, message):
    print("=" * 60)
    print(f"[ALERT] {subject}")
    print(message)
    print("=" * 60)


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

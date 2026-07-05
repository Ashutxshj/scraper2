"""Stage 5 — CSV delivery, following the wa1.txt report-generator theory:

  build artifact -> base64 attach -> one transactional Resend send -> log send

Mirrored traits:
  * No marketing body: the subject line is repeated as the plain `text`.
  * Subject carries the payload count ("N leads"), like "for N mailboxes".
  * The send is logged best-effort AFTER a successful delivery
    (sends_log.jsonl here, standing in for Mongo `report_sends`).
  * Delivery failure is logged, never fatal — the CSV always survives on disk.
"""

import base64
import json
import os
from datetime import datetime, timezone

import config


def _log_send(record: dict) -> None:
    """Best-effort JSONL append — the report_sends analog. Never raises."""
    try:
        os.makedirs(os.path.dirname(config.SENDS_LOG_FILE) or ".", exist_ok=True)
        with open(config.SENDS_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"[delivery] WARN: could not write send log: {exc}")


def send_csv(csv_path: str, lead_count: int) -> bool:
    """Email the CSV as a base64 attachment via Resend. Returns True on success."""
    if not config.RESEND_API_KEY:
        print("[delivery] RESEND_API_KEY not set — skipping email "
              f"(CSV is on disk at {csv_path})")
        return False

    import resend
    resend.api_key = config.RESEND_API_KEY

    with open(csv_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode("ascii")

    filename = os.path.basename(csv_path)
    subject = f"Your Delhi NCR leads CSV is here ({lead_count} lead{'s' if lead_count != 1 else ''})"

    print(f"[delivery] sending {filename} ({lead_count} leads) to {config.RECIPIENT_EMAIL}")
    try:
        result = resend.Emails.send({
            "from": config.RESEND_FROM_EMAIL,
            "to": [config.RECIPIENT_EMAIL],
            "subject": subject,
            "text": subject,  # no HTML body — the value IS the attachment
            "attachments": [{"filename": filename, "content": content_b64}],
        })
    except Exception as exc:
        print(f"[delivery] ERROR: Resend send failed: {exc}")
        print(f"[delivery] CSV preserved at {csv_path}")
        return False

    send_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)
    print(f"[delivery] email sent to {config.RECIPIENT_EMAIL} (resend id: {send_id})")
    _log_send({
        "to": config.RECIPIENT_EMAIL.lower(),
        "filename": filename,
        "leadCount": lead_count,
        "resendId": send_id,
        "sentAt": datetime.now(timezone.utc).isoformat(),
    })
    return True

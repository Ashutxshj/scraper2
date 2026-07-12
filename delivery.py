"""Stage 5 — report delivery, following the wa1.txt report-generator theory:

  build artifact -> base64 attach -> one transactional Resend send -> log send

Mirrored traits:
  * No marketing body: the subject line is repeated as the plain `text`.
  * Subject carries the payload counts ("X Goldenrod, Y New Bark").
  * The send is logged best-effort AFTER a successful delivery
    (sends_log.jsonl here, standing in for Mongo `report_sends`).
  * Delivery failure is logged, never fatal — the files always survive on disk.
"""

import base64
import json
import os
from datetime import datetime, timezone

import config
import master_registry


def _log_send(record: dict) -> None:
    """Best-effort JSONL append — the report_sends analog. Never raises."""
    try:
        os.makedirs(os.path.dirname(config.SENDS_LOG_FILE) or ".", exist_ok=True)
        with open(config.SENDS_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"[delivery] WARN: could not write send log: {exc}")


def send_master(new_leads: int, goldenrod: int = 0, new_bark: int = 0) -> bool:
    """Email the master workbook as a base64 attachment. True on success."""
    path = master_registry.MASTER_FILE
    if not config.RESEND_API_KEY or not config.RECIPIENT_EMAIL:
        print("[delivery] RESEND_API_KEY/RECIPIENT_EMAIL not set — skipping email "
              f"(master is on disk at {path})")
        return False
    if not os.path.exists(path):
        print(f"[delivery] no master workbook at {path} — nothing to send")
        return False

    import resend
    resend.api_key = config.RESEND_API_KEY

    with open(path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode("ascii")

    filename = os.path.basename(path)
    total = len(master_registry.load_rows())
    subject = (f"Delhi NCR no-website leads: {new_leads} new "
               f"({goldenrod} Goldenrod, {new_bark} New Bark) — master holds {total}")

    print(f"[delivery] sending {filename} ({new_leads} new) to {config.RECIPIENT_EMAIL}")
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
        print(f"[delivery] master preserved at {path}")
        return False

    send_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)
    print(f"[delivery] email sent to {config.RECIPIENT_EMAIL} (resend id: {send_id})")
    _log_send({
        "to": config.RECIPIENT_EMAIL.lower(),
        "filename": filename,
        "newLeads": new_leads,
        "totalLeads": total,
        "goldenrod": goldenrod,
        "newBark": new_bark,
        "resendId": send_id,
        "sentAt": datetime.now(timezone.utc).isoformat(),
    })
    return True

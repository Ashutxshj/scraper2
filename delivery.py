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


def _log_send(record: dict) -> None:
    """Best-effort JSONL append — the report_sends analog. Never raises."""
    try:
        os.makedirs(os.path.dirname(config.SENDS_LOG_FILE) or ".", exist_ok=True)
        with open(config.SENDS_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"[delivery] WARN: could not write send log: {exc}")


def send_report(paths: list[str], goldenrod: int, new_bark: int) -> bool:
    """Email the report files (XLSX + CSV) as base64 attachments via Resend.
    Returns True on success."""
    if not config.RESEND_API_KEY:
        print("[delivery] RESEND_API_KEY not set — skipping email "
              f"(files are on disk: {', '.join(paths)})")
        return False

    import resend
    resend.api_key = config.RESEND_API_KEY

    attachments = []
    for path in paths:
        with open(path, "rb") as f:
            attachments.append({
                "filename": os.path.basename(path),
                "content": base64.b64encode(f.read()).decode("ascii"),
            })

    total = goldenrod + new_bark
    subject = (f"Delhi NCR no-website leads: {total} total "
               f"({goldenrod} Goldenrod, {new_bark} New Bark)")

    print(f"[delivery] sending {len(attachments)} file(s) "
          f"({total} leads) to {config.RECIPIENT_EMAIL}")
    try:
        result = resend.Emails.send({
            "from": config.RESEND_FROM_EMAIL,
            "to": [config.RECIPIENT_EMAIL],
            "subject": subject,
            "text": subject,  # no HTML body — the value IS the attachment
            "attachments": attachments,
        })
    except Exception as exc:
        print(f"[delivery] ERROR: Resend send failed: {exc}")
        print(f"[delivery] files preserved at {', '.join(paths)}")
        return False

    send_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)
    print(f"[delivery] email sent to {config.RECIPIENT_EMAIL} (resend id: {send_id})")
    _log_send({
        "to": config.RECIPIENT_EMAIL.lower(),
        "filenames": [os.path.basename(p) for p in paths],
        "leadCount": total,
        "goldenrod": goldenrod,
        "newBark": new_bark,
        "resendId": send_id,
        "sentAt": datetime.now(timezone.utc).isoformat(),
    })
    return True

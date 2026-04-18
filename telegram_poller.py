"""
telegram_poller.py — Poll Telegram for APPLY/REJECT/SKIP commands and process them.

Runs after the daily job scan. Polls for up to POLL_MINUTES minutes,
processes any commands received, then exits cleanly.

Usage:
    python telegram_poller.py
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import httpx

from pipeline import WorkflowOrchestrator
from notifier import send_telegram

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("Poller")

TELEGRAM_BASE = "https://api.telegram.org/bot{token}/{method}"
POLL_MINUTES = int(os.getenv("POLL_MINUTES", "10"))
POLL_INTERVAL = 3  # seconds between getUpdates calls


def _get(method: str, params: dict | None = None) -> dict:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    url = TELEGRAM_BASE.format(token=token, method=method)
    try:
        resp = httpx.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.warning("Telegram %s failed: %s", method, exc)
        return {}


def _get_updates(offset: int | None = None) -> list[dict]:
    params: dict = {"timeout": 2, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    data = _get("getUpdates", params)
    return data.get("result", [])


def _parse_command(text: str) -> dict | None:
    """Parse 'APPLY li_123', 'REJECT li_123', 'SKIP li_123'."""
    import re
    text = (text or "").strip()
    match = re.match(r"^(APPLY|REJECT|SKIP)\s+([A-Za-z0-9_\-]+)$", text, re.IGNORECASE)
    if not match:
        return None
    return {"action": match.group(1).upper(), "job_id": match.group(2)}


def poll_and_process() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        log.error("Telegram credentials not configured — skipping poll")
        return

    orchestrator = WorkflowOrchestrator()
    deadline = time.time() + POLL_MINUTES * 60
    offset: int | None = None
    processed: set[int] = set()

    send_telegram(
        f"⏳ Waiting {POLL_MINUTES} min for your APPLY/REJECT/SKIP replies.\n"
        "Reply with e.g. <code>APPLY li_123456</code> to act on a job."
    )
    log.info("Polling Telegram for %s minutes...", POLL_MINUTES)

    while time.time() < deadline:
        updates = _get_updates(offset)

        for update in updates:
            update_id = update.get("update_id", 0)
            # Advance offset immediately so we never re-process this update
            if offset is None or update_id >= offset:
                offset = update_id + 1

            if update_id in processed:
                continue
            processed.add(update_id)

            message = update.get("message", {})
            # Only process messages from the configured chat
            if str(message.get("chat", {}).get("id", "")) != chat_id:
                continue

            text = message.get("text", "")
            command = _parse_command(text)
            if not command:
                log.info("Ignored non-command message: %s", text[:50])
                continue

            job_id = command["job_id"]
            action = command["action"]
            log.info("Processing %s for job %s", action, job_id)

            try:
                result = orchestrator.decide(job_id=job_id, action=action)
                job = result.get("job", {})
                title = job.get("title", job_id)
                company = job.get("company", "")

                if action == "APPLY":
                    packet = result.get("application_packet", {})
                    cover = packet.get("cover_letter", "")
                    summary = packet.get("tailored_resume", {}).get("summary", "")
                    skills = ", ".join(packet.get("tailored_resume", {}).get("skills", [])[:8])

                    send_telegram(
                        f"✅ <b>Application packet ready!</b>\n\n"
                        f"<b>{title}</b> @ {company}\n\n"
                        f"<b>Tailored Summary:</b>\n{summary}\n\n"
                        f"<b>Key Skills:</b> {skills}\n\n"
                        f"<b>Cover Letter:</b>\n{cover[:800]}{'...' if len(cover) > 800 else ''}\n\n"
                        f"<a href=\"{job.get('link', '#')}\">👉 Open job to apply manually</a>\n\n"
                        "⚠️ Auto-submit is disabled. Review and apply manually."
                    )
                elif action == "REJECT":
                    send_telegram(f"❌ Rejected: <b>{title}</b> @ {company}")
                elif action == "SKIP":
                    send_telegram(f"⏭ Skipped: <b>{title}</b> @ {company}")

            except KeyError:
                send_telegram(f"⚠️ Job ID <code>{job_id}</code> not found. It may be from a previous run.")
            except Exception as exc:
                log.exception("Error processing %s %s: %s", action, job_id, exc)
                send_telegram(f"⚠️ Error processing {action} for {job_id}: {exc}")

        time.sleep(POLL_INTERVAL)

    send_telegram("⏰ Decision window closed. Run the bot again tomorrow for new jobs.")
    log.info("Polling complete.")


if __name__ == "__main__":
    poll_and_process()

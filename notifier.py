"""
notifier.py — Telegram notifications and simple command parsing.
"""

from __future__ import annotations

import html
import os
import re
import logging
from typing import Optional

import httpx

log = logging.getLogger("Notifier")
TELEGRAM_BASE = "https://api.telegram.org/bot{token}/{method}"


def _telegram_request(method: str, payload: dict) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        log.warning("Telegram token not configured")
        return False
    try:
        resp = httpx.post(
            TELEGRAM_BASE.format(token=token, method=method),
            json=payload,
            timeout=15,
        )
        if not resp.is_success:
            log.error("Telegram %s error: %s %s", method, resp.status_code, resp.text)
            return False
        return True
    except Exception as exc:
        log.error("Telegram %s failed: %s", method, exc)
        return False


def send_telegram(message: str, reply_markup: Optional[dict] = None) -> bool:
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        log.warning("Telegram chat id not configured")
        return False
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _telegram_request("sendMessage", payload)


def send_job_card(job: dict) -> bool:
    title = html.escape(job["title"])
    company = html.escape(job["company"])
    location = html.escape(job.get("location", ""))
    reason = html.escape(job.get("reason", ""))
    source = job.get("source", "")
    easy_apply = job.get("easy_apply", True)
    score = job.get("score", 0)
    job_id = job["id"]

    # Source badge
    if source == "LinkedIn" and easy_apply:
        badge = "⚡ LinkedIn Easy Apply"
    elif source == "Naukri":
        badge = "🇮🇳 Naukri"
    elif source == "Indeed":
        badge = "🌍 Indeed Remote"
    else:
        badge = html.escape(source)

    # Score emoji
    score_emoji = "🔥" if score >= 80 else "✅" if score >= 65 else "🟡"

    message = (
        f"📌 <b>{title}</b>\n"
        f"🏢 {company}\n"
        f"📍 {location}\n"
        f"{score_emoji} Match Score: <b>{score}/100</b>\n"
        f"🏷 {badge}\n"
        f"💡 {reason}\n"
        f"🔗 <a href=\"{html.escape(job.get('link', '#'))}\">View Job</a>"
    )

    # Inline buttons — stay attached to the message, no keyboard clutter
    inline_keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Apply", "callback_data": f"apply_{job_id}"},
                {"text": "❌ Reject", "callback_data": f"reject_{job_id}"},
                {"text": "⏭ Skip", "callback_data": f"skip_{job_id}"},
            ],
            [
                {"text": "📄 Preview Resume", "callback_data": f"resume_{job_id}"},
                {"text": "❓ View Q&A", "callback_data": f"qa_{job_id}"},
            ],
        ]
    }
    return send_telegram(message, reply_markup=inline_keyboard)


def notify_jobs(results: list) -> None:
    if not results:
        send_telegram("Job Bot ran, but there were no new matches above your threshold.")
        return

    lines = [f"<b>Job Bot Report</b> — {len(results)} new shortlisted jobs"]
    for result in results[:5]:
        lines.append(
            f"\n• <b>{html.escape(result['job_title'])}</b> @ {html.escape(result['company'])}\n"
            f"  Score: {result['fit_score']}/100 | {html.escape(result.get('reasoning', ''))}\n"
            f"  <a href=\"{html.escape(result.get('apply_url', '#'))}\">Apply link</a>"
        )
    send_telegram("\n".join(lines))

    for result in results[:3]:
        send_job_card(
            {
                "id": result["job_id"],
                "title": result["job_title"],
                "company": result["company"],
                "location": result.get("location", ""),
                "score": result["fit_score"],
                "reason": result.get("reasoning", ""),
                "link": result.get("apply_url", "#"),
            }
        )


def answer_callback_query(callback_query_id: str, text: str = "") -> bool:
    """Acknowledge a Telegram inline button press."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return False
    try:
        resp = httpx.post(
            TELEGRAM_BASE.format(token=token, method="answerCallbackQuery"),
            json={"callback_query_id": callback_query_id, "text": text},
            timeout=10,
        )
        return resp.is_success
    except Exception:
        return False


def parse_telegram_command(update: dict) -> Optional[dict]:
    """Parse both text commands and inline button callback queries."""
    # Handle inline button callback
    callback = update.get("callback_query", {})
    if callback:
        data = (callback.get("data") or "").strip()
        match = re.match(r"^(apply|reject|skip|resume|qa)_(.+)$", data, re.IGNORECASE)
        if match:
            return {
                "action": match.group(1).upper(),
                "job_id": match.group(2),
                "callback_query_id": callback.get("id", ""),
                "is_callback": True,
            }
        return None

    # Handle plain text commands (fallback)
    message = update.get("message", {})
    text = (message.get("text") or "").strip()
    match = re.match(r"^(APPLY|REJECT|SKIP)\s+([A-Za-z0-9_\-]+)$", text, re.IGNORECASE)
    if not match:
        return None
    return {
        "action": match.group(1).upper(),
        "job_id": match.group(2),
        "is_callback": False,
    }

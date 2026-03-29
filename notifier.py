"""
notifier.py — Send Telegram notifications for matched jobs.
"""

import os
import httpx
import logging

log = logging.getLogger("Notifier")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram(message: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        log.warning("Telegram not configured — skipping notification")
        return False
    try:
        resp = httpx.post(
            TELEGRAM_API.format(token=token),
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        log.error(f"Telegram error: {e}")
        return False


def notify_jobs(results: list):
    """Send a Telegram summary of APPLY-worthy jobs."""
    apply_jobs = [r for r in results if r.get("decision") == "APPLY"]
    maybe_jobs = [r for r in results if r.get("decision") == "MAYBE"]

    if not apply_jobs and not maybe_jobs:
        send_telegram("\U0001f916 Job Bot ran — no strong matches found this round. Will check again soon.")
        return

    lines = [f"\U0001f916 <b>Job Bot Report</b> — {len(apply_jobs)} APPLY, {len(maybe_jobs)} MAYBE\n"]

    for r in apply_jobs[:5]:
        lines.append(
            f"\u2705 <b>{r['job_title']}</b> @ {r['company']}\n"
            f"   Score: {r['fit_score']}/100\n"
            f"   {r.get('reasoning', '')}\n"
            f"   \U0001f517 <a href='{r.get('apply_url', '#')}'>Apply Now</a>\n"
        )

    for r in maybe_jobs[:3]:
        lines.append(
            f"\U0001f7e1 <b>{r['job_title']}</b> @ {r['company']}\n"
            f"   Score: {r['fit_score']}/100\n"
            f"   \U0001f517 <a href='{r.get('apply_url', '#')}'>View Job</a>\n"
        )

    send_telegram("\n".join(lines))

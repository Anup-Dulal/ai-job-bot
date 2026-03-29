"""\nnotifier.py — Telegram notifications with source, recency and company info.\n"""

import os
import httpx
import logging

log = logging.getLogger("Notifier")
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram(message: str) -> bool:
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        log.warning("Telegram not configured")
        return False
    try:
        resp = httpx.post(
            TELEGRAM_API.format(token=token),
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10,
        )
        if not resp.is_success:
            log.error(f"Telegram error: {resp.status_code} — {resp.text}")
            return False
        log.info("Telegram sent")
        return True
    except Exception as e:
        log.error(f"Telegram error: {e}")
        return False


def notify_jobs(results: list):
    apply_jobs = [r for r in results if r.get("decision") == "APPLY"]
    maybe_jobs = [r for r in results if r.get("decision") == "MAYBE"]

    if not apply_jobs and not maybe_jobs:
        send_telegram("\U0001f916 Job Bot ran — no strong matches this round. Next check in 1 hour.")
        return

    lines = [f"\U0001f916 <b>Job Bot Report</b> — {len(apply_jobs)} APPLY, {len(maybe_jobs)} MAYBE\n"]

    for r in apply_jobs[:5]:
        days = r.get('days_ago', '?')
        freshness = "\U0001f7e2 Today" if days == 0 else f"\U0001f551 {days}d ago"
        source = r.get('source', '')
        lines.append(
            f"\u2705 <b>{r['job_title']}</b> @ {r['company']}\n"
            f"   {r.get('location','')} | {source} | {freshness}\n"
            f"   Score: {r['fit_score']}/100 | {r.get('reasoning','')}\n"
            f"   \U0001f517 <a href='{r.get('apply_url','#')}'>Apply Now</a>\n"
        )

    for r in maybe_jobs[:3]:
        days = r.get('days_ago', '?')
        freshness = "\U0001f7e2 Today" if days == 0 else f"\U0001f551 {days}d ago"
        lines.append(
            f"\U0001f7e1 <b>{r['job_title']}</b> @ {r['company']}\n"
            f"   {r.get('location','')} | {r.get('source','')} | {freshness}\n"
            f"   Score: {r['fit_score']}/100\n"
            f"   \U0001f517 <a href='{r.get('apply_url','#')}'>View Job</a>\n"
        )

    send_telegram("\n".join(lines))

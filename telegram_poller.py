"""
telegram_poller.py — Poll Telegram for inline button callbacks and text commands.

Handles:
  - APPLY / REJECT / SKIP  → decision workflow
  - RESUME                 → send tailored resume preview
  - QA                     → send LLM-generated Q&A answers

Runs after the daily job scan for POLL_MINUTES (default 10).
"""

from __future__ import annotations

import logging
import os
import time

import httpx

from notifier import answer_callback_query, send_telegram
from pipeline import WorkflowOrchestrator
from resume_profile import RESUME

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
    params: dict = {"timeout": 2, "allowed_updates": ["message", "callback_query"]}
    if offset is not None:
        params["offset"] = offset
    data = _get("getUpdates", params)
    return data.get("result", [])


def _handle_resume_preview(job_id: str, orchestrator: WorkflowOrchestrator) -> None:
    """Generate and send a tailored resume preview for a job."""
    try:
        from storage import get_job
        job = get_job(job_id)
        if not job:
            send_telegram(f"⚠️ Job <code>{job_id}</code> not found.")
            return

        send_telegram(f"⏳ Generating tailored resume for <b>{job['title']}</b> @ {job['company']}...")
        tailored = orchestrator.resume_optimizer.tailor_resume(job)

        summary = tailored.get("summary", "")
        skills = ", ".join(tailored.get("skills", [])[:10])
        bullets = tailored.get("experience_bullets", [])[:5]
        bullets_text = "\n".join(f"  - {b}" for b in bullets)
        changes = tailored.get("changes", [])[:3]
        changes_text = "\n".join(f"  - {c}" for c in changes)

        send_telegram(
            f"📄 <b>Tailored Resume Preview</b>\n"
            f"<b>For:</b> {job['title']} @ {job['company']}\n\n"
            f"<b>Summary:</b>\n{summary}\n\n"
            f"<b>Key Skills:</b>\n{skills}\n\n"
            f"<b>Experience Highlights:</b>\n{bullets_text}\n\n"
            f"<b>Changes Made:</b>\n{changes_text}\n\n"
            f"Reply <code>APPLY {job_id}</code> to generate full PDF and application packet."
        )
    except Exception as exc:
        log.exception("Resume preview failed: %s", exc)
        send_telegram(f"⚠️ Could not generate resume preview: {exc}")


def _handle_qa_preview(job_id: str, orchestrator: WorkflowOrchestrator) -> None:
    """Generate and send LLM Q&A answers for a job."""
    try:
        from storage import get_job
        from agent import JobApplicationAgent
        job = get_job(job_id)
        if not job:
            send_telegram(f"⚠️ Job <code>{job_id}</code> not found.")
            return

        agent = JobApplicationAgent()
        common_questions = [
            "Why do you want this role?",
            "Describe your experience with Spring Boot",
            "What is your expected salary?",
            "How many years of experience do you have?",
            "Are you open to relocation?",
            "What is your notice period?",
        ]

        send_telegram(f"⏳ Generating Q&A for <b>{job['title']}</b> @ {job['company']}...")

        lines = [f"❓ <b>Q&A for {job['title']} @ {job['company']}</b>\n"]
        for q in common_questions:
            answer = agent.answer_form_question(q, job_context=job)
            lines.append(f"<b>Q:</b> {q}\n<b>A:</b> {answer}\n")

        send_telegram("\n".join(lines))
    except Exception as exc:
        log.exception("Q&A preview failed: %s", exc)
        send_telegram(f"⚠️ Could not generate Q&A: {exc}")


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
        f"⏳ <b>Decision window open for {POLL_MINUTES} minutes.</b>\n"
        "Tap the buttons on each job card to act.\n"
        "📄 Preview Resume | ❓ View Q&A | ✅ Apply | ❌ Reject | ⏭ Skip"
    )
    log.info("Polling Telegram for %s minutes...", POLL_MINUTES)

    while time.time() < deadline:
        updates = _get_updates(offset)

        for update in updates:
            update_id = update.get("update_id", 0)
            # Advance offset immediately — prevents re-processing
            if offset is None or update_id >= offset:
                offset = update_id + 1

            if update_id in processed:
                continue
            processed.add(update_id)

            # Determine source: callback_query or message
            callback = update.get("callback_query", {})
            message = update.get("message", {})

            # Filter by chat_id
            source_chat = (
                str(callback.get("message", {}).get("chat", {}).get("id", ""))
                if callback
                else str(message.get("chat", {}).get("id", ""))
            )
            if source_chat != chat_id:
                continue

            # Parse the action
            if callback:
                data = (callback.get("data") or "").strip()
                import re
                match = re.match(r"^(apply|reject|skip|resume|qa)_(.+)$", data, re.IGNORECASE)
                if not match:
                    continue
                action = match.group(1).upper()
                job_id = match.group(2)
                cb_id = callback.get("id", "")
            else:
                text = (message.get("text") or "").strip()
                import re
                match = re.match(r"^(APPLY|REJECT|SKIP)\s+([A-Za-z0-9_\-]+)$", text, re.IGNORECASE)
                if not match:
                    continue
                action = match.group(1).upper()
                job_id = match.group(2)
                cb_id = ""

            log.info("Processing %s for job %s", action, job_id)

            # Acknowledge inline button immediately
            if cb_id:
                answer_callback_query(cb_id, text=f"{action.title()} received!")

            # Handle action
            if action == "RESUME":
                _handle_resume_preview(job_id, orchestrator)
                continue

            if action == "QA":
                _handle_qa_preview(job_id, orchestrator)
                continue

            # APPLY / REJECT / SKIP
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
                    send_telegram(f"❌ <b>Rejected:</b> {title} @ {company}")
                elif action == "SKIP":
                    send_telegram(f"⏭ <b>Skipped:</b> {title} @ {company}")

            except KeyError:
                send_telegram(f"⚠️ Job <code>{job_id}</code> not found. It may be from a previous run.")
            except Exception as exc:
                log.exception("Error processing %s %s: %s", action, job_id, exc)
                send_telegram(f"⚠️ Error processing {action} for {job_id}: {exc}")

        time.sleep(POLL_INTERVAL)

    send_telegram("⏰ Decision window closed. New jobs will arrive tomorrow at 9 AM IST.")
    log.info("Polling complete.")


if __name__ == "__main__":
    poll_and_process()

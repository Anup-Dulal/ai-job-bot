"""
scheduler.py — Orchestrates the full step-wise AI pipeline.
Step 1: Groq generates keywords
Step 2: Fetch from LinkedIn + Naukri/Adzuna
Step 3: Rule-based pre-filter (fast, free)
Step 4: Groq deep scores filtered jobs
Step 5: Groq enriches APPLY jobs only
Step 6: Telegram notification
"""

import os
import time
import logging
from datetime import datetime
from naukri_fetcher import fetch_all_jobs
from pre_filter import pre_filter
from agent import JobApplicationAgent
from notifier import notify_jobs, send_telegram

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("Scheduler")


def run_once():
    log.info("=" * 60)
    log.info(f"Pipeline started at {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Step 1 + 2: Smart fetch (keywords generated inside fetch_all_jobs)
    raw_jobs = fetch_all_jobs()
    log.info(f"[Step 2] Raw jobs fetched: {len(raw_jobs)}")

    if not raw_jobs:
        send_telegram("\u26a0\ufe0f Job Bot: No jobs fetched this run. Will retry next hour.")
        return

    # Step 3: Pre-filter (rule-based, instant, free)
    filtered_jobs = pre_filter(raw_jobs)
    log.info(f"[Step 3] After pre-filter: {len(filtered_jobs)} jobs to deep-score")

    if not filtered_jobs:
        send_telegram("\U0001f916 Job Bot: Fetched jobs but none passed relevance filter. Adjusting next run.")
        return

    # Step 4 + 5: Deep score + enrich
    agent = JobApplicationAgent()
    results = agent.batch_process(filtered_jobs)

    apply_count = sum(1 for r in results if r["decision"] == "APPLY")
    maybe_count = sum(1 for r in results if r["decision"] == "MAYBE")
    skip_count  = len(results) - apply_count - maybe_count
    log.info(f"Results: {apply_count} APPLY, {maybe_count} MAYBE, {skip_count} SKIP")

    # Step 6: Notify
    notify_jobs(results)
    log.info("[Step 6] Telegram notification sent")


def main():
    interval = int(os.getenv("SCHEDULE_MINUTES", "60")) * 60
    send_telegram("\U0001f916 Job Bot <b>online</b>! Running 6-step AI pipeline. First search starting now...")
    while True:
        try:
            run_once()
        except Exception as e:
            log.error(f"Pipeline error: {e}")
            send_telegram(f"\u274c Job Bot pipeline error: {e}")
        log.info(f"Sleeping {interval // 60} min until next run...")
        time.sleep(interval)


if __name__ == "__main__":
    main()

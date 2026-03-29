"""
scheduler.py — Runs the job search loop on a schedule.
Start this as the main process on Render/Railway.
"""

import os
import time
import logging
from datetime import datetime
from naukri_fetcher import fetch_all_jobs
from agent import JobApplicationAgent
from notifier import notify_jobs, send_telegram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
)
log = logging.getLogger("Scheduler")


def run_once():
    log.info("=" * 50)
    log.info(f"Job search started at {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # 1. Fetch jobs from Naukri
    jobs = fetch_all_jobs()
    log.info(f"Fetched {len(jobs)} unique jobs")

    if not jobs:
        send_telegram("\u26a0\ufe0f Job Bot: Could not fetch jobs from Naukri. Will retry next run.")
        return

    # 2. Run agent on all jobs
    agent = JobApplicationAgent()
    results = agent.batch_process(jobs)

    # Attach apply_url from original job data
    job_map = {j["id"]: j for j in jobs}
    for r in results:
        r["apply_url"] = job_map.get(r["job_id"], {}).get("apply_url", "#")

    apply_count = sum(1 for r in results if r["decision"] == "APPLY")
    maybe_count = sum(1 for r in results if r["decision"] == "MAYBE")
    log.info(f"Results: {apply_count} APPLY, {maybe_count} MAYBE, {len(results)-apply_count-maybe_count} SKIP")

    # 3. Notify via Telegram
    notify_jobs(results)
    log.info("Telegram notification sent")


def main():
    interval = int(os.getenv("SCHEDULE_MINUTES", "60")) * 60
    send_telegram("\U0001f916 Job Bot is now <b>online</b> on Render! First search starting now...")

    while True:
        try:
            run_once()
        except Exception as e:
            log.error(f"Run failed: {e}")
            send_telegram(f"\u274c Job Bot error: {e}")
        log.info(f"Sleeping {interval // 60} minutes until next run...")
        time.sleep(interval)


if __name__ == "__main__":
    main()

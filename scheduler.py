"""
scheduler.py — Runs the job pipeline once or in a loop.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime

from notifier import send_telegram
from pipeline import WorkflowOrchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("Scheduler")
orchestrator = WorkflowOrchestrator()


def run_once() -> dict:
    log.info("=" * 60)
    log.info("Pipeline started at %s", datetime.now().strftime("%Y-%m-%d %H:%M"))
    result = orchestrator.run_once(top_n=int(os.getenv("TOP_JOBS_TO_NOTIFY", "10")))
    log.info(
        "Fetched=%s Ranked=%s Shortlisted=%s NewlyNotified=%s",
        result["fetched"],
        result["ranked"],
        result["shortlisted"],
        len(result["new_jobs"]),
    )
    return result


def run_forever() -> None:
    interval_seconds = int(os.getenv("SCHEDULE_MINUTES", "60")) * 60
    send_telegram("Job Bot is online and starting the scheduled pipeline loop.")
    while True:
        try:
            run_once()
        except Exception as exc:
            log.exception("Pipeline loop failed: %s", exc)
            send_telegram(f"Job Bot pipeline error: {exc}")
        log.info("Sleeping for %s minutes", interval_seconds // 60)
        time.sleep(interval_seconds)


def main() -> None:
    mode = os.getenv("RUN_MODE", "loop").strip().lower()
    if mode == "once":
        run_once()
    else:
        run_forever()


if __name__ == "__main__":
    main()

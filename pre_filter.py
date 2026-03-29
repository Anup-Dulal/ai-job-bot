"""
pre_filter.py — Step 3: Fast rule-based pre-filter before hitting Groq.
Drops irrelevant jobs instantly — saves Groq quota and improves accuracy.
"""

import re
import logging
from resume_profile import RESUME

log = logging.getLogger("PreFilter")

# Must contain at least one of these in title or description
RELEVANT_KEYWORDS = [
    "java", "spring", "backend", "microservice", "software engineer",
    "software developer", "full stack", "api developer", "aws",
]

# Immediately disqualify if title contains these
SKIP_TITLE_KEYWORDS = [
    "javascript", "js developer", "react developer", "angular", "vue",
    "frontend", "front-end", "ios", "android", "mobile", "qa ", "tester",
    "data scientist", "data analyst", "machine learning", "ml engineer",
    "devops", "sre ", "network", "hardware", "embedded", "sap ",
    "salesforce", "oracle dba", "php", "ruby", "golang", "rust",
    "intern", "fresher", "trainee", "0-1 year", "0 - 1 year",
]

# Skip if experience required is way off
EXP_YEARS = RESUME["experience_years"]  # 4


def _exp_match(text: str) -> bool:
    """Return False if job clearly requires experience outside 2-8 year range."""
    m = re.search(r"(\d+)\s*[-\u2013]\s*(\d+)\s*years?", text.lower())
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if hi < 2 or lo > 8:  # too junior or too senior
            return False
    m2 = re.search(r"(\d+)\+\s*years?", text.lower())
    if m2:
        req = int(m2.group(1))
        if req > 8:
            return False
    return True


def pre_filter(jobs: list) -> list:
    """
    Step 3: Filter jobs before sending to Groq.
    Returns only jobs worth deep-scoring.
    """
    kept, dropped = [], []
    for job in jobs:
        title = job.get("title", "").lower()
        desc  = job.get("description", "").lower()
        combined = f"{title} {desc}"

        # Hard skip on title keywords
        if any(kw in title for kw in SKIP_TITLE_KEYWORDS):
            dropped.append(job["title"])
            continue

        # Must have at least one relevant keyword
        if not any(kw in combined for kw in RELEVANT_KEYWORDS):
            dropped.append(job["title"])
            continue

        # Experience range check
        if not _exp_match(combined):
            dropped.append(job["title"])
            continue

        kept.append(job)

    log.info(f"[Step 3] Pre-filter: {len(kept)} kept, {len(dropped)} dropped")
    if dropped:
        log.info(f"  Dropped: {dropped[:5]}{'...' if len(dropped) > 5 else ''}")
    return kept

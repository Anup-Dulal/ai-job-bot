"""
naukri_fetcher.py — Fetch jobs from Naukri search API
No login needed, no browser, works on Railway/Render.
"""

import os
import httpx
import logging

log = logging.getLogger("Naukri")

NAUKRI_SEARCH_URL = "https://www.naukri.com/jobapi/v3/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "appid": "109",
    "systemid": "109",
}


def fetch_jobs(keyword: str, location: str = "", max_results: int = 30) -> list:
    """Fetch jobs from Naukri for a given keyword and location."""
    params = {
        "noOfResults": max_results,
        "urlType": "search_by_keyword",
        "searchType": "adv",
        "keyword": keyword,
        "location": location,
        "pageNo": 1,
        "sort": "r",  # relevance
        "xp": "3,6",  # 3-6 years experience
        "jobAge": 7,  # posted in last 7 days
    }
    try:
        resp = httpx.get(NAUKRI_SEARCH_URL, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        jobs_raw = data.get("jobDetails", [])
        jobs = []
        for j in jobs_raw:
            jobs.append({
                "id": str(j.get("jobId", "")),
                "title": j.get("title", ""),
                "company": j.get("companyName", ""),
                "location": ", ".join(j.get("placeholders", [{}])[0].get("label", "").split(",")[:2]) if j.get("placeholders") else "",
                "description": j.get("jobDescription", ""),
                "apply_url": f"https://www.naukri.com{j.get('jdURL', '')}",
                "posted": j.get("footerPlaceholderLabel", ""),
            })
        log.info(f"Naukri: {len(jobs)} jobs for '{keyword}' in '{location}'")
        return jobs
    except Exception as e:
        log.error(f"Naukri fetch error: {e}")
        return []


def fetch_all_jobs() -> list:
    """Fetch jobs for all keywords and locations from env vars."""
    keywords = os.getenv("SEARCH_KEYWORDS", "Java Backend Developer").split("|")
    locations = os.getenv("SEARCH_LOCATIONS", "Noida|Bangalore|Remote").split("|")
    max_per_run = int(os.getenv("MAX_JOBS_PER_RUN", "30"))

    seen_ids = set()
    all_jobs = []

    for keyword in keywords[:3]:  # limit to 3 keywords to avoid hammering
        for location in locations[:3]:
            jobs = fetch_jobs(keyword.strip(), location.strip(), max_results=10)
            for job in jobs:
                if job["id"] and job["id"] not in seen_ids:
                    seen_ids.add(job["id"])
                    all_jobs.append(job)
            if len(all_jobs) >= max_per_run:
                break
        if len(all_jobs) >= max_per_run:
            break

    return all_jobs[:max_per_run]

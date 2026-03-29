"""
naukri_fetcher.py — Fetch jobs from Naukri using their internal API
Uses proper headers that Naukri expects.
"""

import os
import httpx
import logging

log = logging.getLogger("Naukri")

NAUKRI_SEARCH_URL = "https://www.naukri.com/jobapi/v3/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.naukri.com/",
    "appid": "109",
    "systemid": "Naukri",
    "gid": "LOCATION,INDUSTRY,EDUCATION,FAREA_ROLE",
    "Connection": "keep-alive",
    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


def fetch_jobs(keyword: str, location: str = "", max_results: int = 20) -> list:
    """Fetch jobs from Naukri for a given keyword and location."""
    params = {
        "noOfResults": max_results,
        "urlType": "search_by_keyword",
        "searchType": "adv",
        "keyword": keyword,
        "location": location,
        "pageNo": 1,
        "sort": "r",
        "xp": "3,6",
        "jobAge": 7,
    }
    try:
        with httpx.Client(follow_redirects=True, timeout=20) as client:
            # First hit the main page to get cookies
            client.get("https://www.naukri.com/", headers={
                "User-Agent": HEADERS["User-Agent"],
                "Accept": "text/html",
            })
            # Now hit the API with cookies in session
            resp = client.get(NAUKRI_SEARCH_URL, params=params, headers=HEADERS)
            resp.raise_for_status()
            data = resp.json()
            jobs_raw = data.get("jobDetails", [])
            jobs = []
            for j in jobs_raw:
                placeholders = j.get("placeholders", [])
                loc = ""
                for p in placeholders:
                    if p.get("type") == "location":
                        loc = p.get("label", "")
                        break
                jobs.append({
                    "id": str(j.get("jobId", "")),
                    "title": j.get("title", ""),
                    "company": j.get("companyName", ""),
                    "location": loc,
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

    for keyword in keywords[:3]:
        for location in locations[:3]:
            jobs = fetch_jobs(keyword.strip(), location.strip())
            for job in jobs:
                if job["id"] and job["id"] not in seen_ids:
                    seen_ids.add(job["id"])
                    all_jobs.append(job)
            if len(all_jobs) >= max_per_run:
                break
        if len(all_jobs) >= max_per_run:
            break

    return all_jobs[:max_per_run]

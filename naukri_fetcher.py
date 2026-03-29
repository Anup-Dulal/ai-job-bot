"""
naukri_fetcher.py — Fetch jobs via JSearch API (RapidAPI)
Free tier: 500 requests/month — enough for hourly runs.
Get free key: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
Searches across Naukri, LinkedIn, Indeed, Glassdoor.
"""

import os
import httpx
import logging

log = logging.getLogger("JobFetcher")

JSEARCH_URL = "https://jsearch.p.rapidapi.com/search"


def fetch_jobs(keyword: str, location: str = "", max_results: int = 10) -> list:
    api_key = os.getenv("RAPIDAPI_KEY", "")
    if not api_key:
        log.warning("RAPIDAPI_KEY not set — skipping job fetch")
        return []

    query = f"{keyword} in {location}" if location else keyword
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }
    params = {
        "query": query,
        "page": "1",
        "num_pages": "1",
        "date_posted": "week",
        "employment_types": "FULLTIME",
        "job_requirements": "under_3_years_experience,more_than_3_years_experience",
        "country": "in",
    }
    try:
        resp = httpx.get(JSEARCH_URL, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        jobs_raw = data.get("data", [])[:max_results]
        jobs = []
        for j in jobs_raw:
            jobs.append({
                "id": j.get("job_id", ""),
                "title": j.get("job_title", ""),
                "company": j.get("employer_name", ""),
                "location": f"{j.get('job_city', '')} {j.get('job_state', '')}".strip(),
                "description": j.get("job_description", "")[:2000],
                "apply_url": j.get("job_apply_link", "#"),
                "posted": j.get("job_posted_at_datetime_utc", ""),
            })
        log.info(f"JSearch: {len(jobs)} jobs for '{query}'")
        return jobs
    except Exception as e:
        log.error(f"JSearch fetch error: {e}")
        return []


def fetch_all_jobs() -> list:
    keywords = os.getenv("SEARCH_KEYWORDS", "Java Backend Developer").split("|")
    locations = os.getenv("SEARCH_LOCATIONS", "Noida|Bangalore").split("|")
    max_per_run = int(os.getenv("MAX_JOBS_PER_RUN", "30"))

    seen_ids = set()
    all_jobs = []

    for keyword in keywords[:3]:
        for location in locations[:2]:
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

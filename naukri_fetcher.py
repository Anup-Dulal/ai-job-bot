"""
job_fetcher.py — Fetch jobs from LinkedIn public guest API.
No API key needed, no login, works from any server including Railway.
Groq generates smart search keywords from your resume.
"""

import os
import re
import httpx
import logging
import json
from resume_profile import RESUME, get_resume_text
from llm_client import call_llm

log = logging.getLogger("JobFetcher")

LINKEDIN_GUEST_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def generate_keywords() -> list:
    """Ask Groq to generate best job search keywords from resume."""
    prompt = f"""Based on this resume, generate 4 job search keyword phrases for LinkedIn job search in India.
Focus on role titles and key skills. Keep each phrase short (2-4 words max).
Return ONLY a JSON array of 4 strings.

Resume:
{get_resume_text()}

Example: ["Java Backend Developer", "Spring Boot Microservices", "Java Software Engineer", "Backend Engineer Java"]
Return ONLY the JSON array."""

    result = call_llm(prompt, max_tokens=150, json_mode=False)
    if result:
        try:
            start = result.find('[')
            end = result.rfind(']') + 1
            if start >= 0 and end > start:
                keywords = json.loads(result[start:end])
                if isinstance(keywords, list) and len(keywords) > 0:
                    log.info(f"Groq generated keywords: {keywords}")
                    return keywords
        except Exception as e:
            log.warning(f"Could not parse Groq keywords: {e}")

    # Fallback from resume
    return [r for r in RESUME["ideal_job"]["roles"][:4]]


def parse_jobs_html(html: str) -> list:
    """Parse LinkedIn job cards from HTML response."""
    jobs = []
    # Extract job cards
    cards = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)".*?</li>', html, re.DOTALL)

    # Simpler approach - find all job postings
    job_ids = re.findall(r'urn:li:jobPosting:(\d+)', html)
    titles = re.findall(r'base-search-card__title[^>]*>\s*([^<]+)', html)
    companies = re.findall(r'base-search-card__subtitle[^>]*>.*?<a[^>]*>([^<]+)', html, re.DOTALL)
    locations = re.findall(r'job-search-card__location[^>]*>([^<]+)', html)

    for i, job_id in enumerate(job_ids[:10]):
        title = titles[i].strip() if i < len(titles) else ""
        company = companies[i].strip() if i < len(companies) else ""
        location = locations[i].strip() if i < len(locations) else ""
        if title:
            jobs.append({
                "id": job_id,
                "title": title,
                "company": company,
                "location": location,
                "description": f"{title} at {company} in {location}",
                "apply_url": f"https://www.linkedin.com/jobs/view/{job_id}",
                "posted": "",
            })
    return jobs


def fetch_jobs(keyword: str, location: str = "India") -> list:
    """Fetch jobs from LinkedIn guest API."""
    params = {
        "keywords": keyword,
        "location": location,
        "geoId": "102713980",  # India
        "f_TPR": "r604800",    # last 7 days
        "f_E": "3,4",          # mid-senior level
        "position": 1,
        "pageNum": 0,
    }
    try:
        resp = httpx.get(LINKEDIN_GUEST_URL, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        jobs = parse_jobs_html(resp.text)
        log.info(f"LinkedIn: {len(jobs)} jobs for '{keyword}'")
        return jobs
    except Exception as e:
        log.error(f"LinkedIn fetch error: {e}")
        return []


def fetch_all_jobs() -> list:
    """Main entry: Groq generates keywords → LinkedIn finds jobs → return list."""
    keywords = generate_keywords()
    locations = RESUME["ideal_job"]["locations"][:3]
    max_per_run = int(os.getenv("MAX_JOBS_PER_RUN", "30"))

    seen_ids = set()
    all_jobs = []

    for keyword in keywords:
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

    log.info(f"Total unique jobs fetched: {len(all_jobs)}")
    return all_jobs[:max_per_run]

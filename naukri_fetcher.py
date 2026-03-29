"""
naukri_fetcher.py — Multi-source: LinkedIn + Adzuna (aggregates Naukri/Shine/TimesJobs)
Groq generates smart keywords. Excludes Capgemini. Sorted by recency.
"""

import os
import re
import time
import httpx
import logging
import json
from datetime import datetime, timezone
from resume_profile import RESUME, get_resume_text
from llm_client import call_llm

log = logging.getLogger("JobFetcher")

EXCLUDE_COMPANIES = ["capgemini"]

LINKEDIN_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
ADZUNA_URL   = "https://api.adzuna.com/v1/api/jobs/in/search/1"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ── Groq: generate smart keywords ────────────────────────────────────────
def generate_keywords() -> list:
    prompt = f"""Based on this resume, generate 4 short job search keyword phrases for India job search.
Focus on role titles and key skills. 2-4 words max each.
Return ONLY a JSON array of 4 strings.

Resume:
{get_resume_text()}

Example: ["Java Backend Developer", "Spring Boot Engineer", "Java Microservices", "Backend Engineer Java"]
Return ONLY the JSON array."""
    result = call_llm(prompt, max_tokens=150)
    if result:
        try:
            start, end = result.find('['), result.rfind(']') + 1
            if start >= 0 and end > start:
                kw = json.loads(result[start:end])
                if isinstance(kw, list) and kw:
                    log.info(f"Groq keywords: {kw}")
                    return kw
        except Exception as e:
            log.warning(f"Groq keyword parse error: {e}")
    return RESUME["ideal_job"]["roles"][:4]


# ── Freshness score ───────────────────────────────────────────────────────
def freshness_score(posted_str: str) -> int:
    if not posted_str:
        return 30
    s = posted_str.lower()
    try:
        if "just now" in s or "today" in s: return 0
        m = re.search(r"(\d+)\s*(minute|hour|day|week|month)", s)
        if m:
            n, unit = int(m.group(1)), m.group(2)
            if "minute" in unit or "hour" in unit: return 0
            if "day"   in unit: return n
            if "week"  in unit: return n * 7
            if "month" in unit: return n * 30
        dt = datetime.fromisoformat(posted_str.replace('Z', '+00:00'))
        return (datetime.now(timezone.utc) - dt).days
    except:
        return 30


def is_excluded(company: str) -> bool:
    return any(ex in company.lower() for ex in EXCLUDE_COMPANIES)


# ── LinkedIn fetcher ──────────────────────────────────────────────────────
def parse_linkedin_html(html: str) -> list:
    job_ids   = re.findall(r'urn:li:jobPosting:(\d+)', html)
    titles    = re.findall(r'base-search-card__title[^>]*>\s*([^<]+)', html)
    companies = re.findall(r'base-search-card__subtitle[^>]*>.*?<a[^>]*>([^<]+)', html, re.DOTALL)
    locations = re.findall(r'job-search-card__location[^>]*>([^<]+)', html)
    posted    = re.findall(r'job-search-card__listdate[^>]*>([^<]+)', html)
    jobs = []
    for i, job_id in enumerate(job_ids[:10]):
        title   = titles[i].strip()    if i < len(titles)    else ""
        company = companies[i].strip() if i < len(companies) else ""
        loc     = locations[i].strip() if i < len(locations) else ""
        post    = posted[i].strip()    if i < len(posted)    else ""
        if title and not is_excluded(company):
            jobs.append({
                "id": f"li_{job_id}", "title": title, "company": company,
                "location": loc, "description": f"{title} at {company} in {loc}",
                "apply_url": f"https://www.linkedin.com/jobs/view/{job_id}",
                "posted": post, "days_ago": freshness_score(post), "source": "LinkedIn",
            })
    return jobs


def fetch_linkedin(keyword: str, location: str = "India") -> list:
    try:
        resp = httpx.get(LINKEDIN_URL, params={
            "keywords": keyword, "location": location, "geoId": "102713980",
            "f_TPR": "r604800", "f_E": "3,4", "position": 1, "pageNum": 0,
        }, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        jobs = parse_linkedin_html(resp.text)
        log.info(f"LinkedIn: {len(jobs)} jobs for '{keyword}' in '{location}'")
        return jobs
    except Exception as e:
        log.error(f"LinkedIn error: {e}")
        return []


# ── Adzuna fetcher (aggregates Naukri, Shine, TimesJobs) ─────────────────
def fetch_adzuna(keyword: str, location: str = "India") -> list:
    app_id  = os.getenv("ADZUNA_APP_ID", "")
    app_key = os.getenv("ADZUNA_APP_KEY", "")
    if not app_id or not app_key:
        log.warning("ADZUNA_APP_ID or ADZUNA_APP_KEY not set — skipping Adzuna")
        return []
    try:
        resp = httpx.get(ADZUNA_URL, params={
            "app_id": app_id, "app_key": app_key,
            "results_per_page": 15,
            "what": keyword,
            "where": location,
            "sort_by": "date",          # newest first
            "max_days_old": 7,          # last 7 days only
            "content-type": "application/json",
        }, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        jobs = []
        for j in data.get("results", []):
            company  = j.get("company", {}).get("display_name", "")
            if is_excluded(company):
                continue
            created  = j.get("created", "")
            jobs.append({
                "id": f"az_{j.get('id', '')}",
                "title": j.get("title", ""),
                "company": company,
                "location": j.get("location", {}).get("display_name", location),
                "description": j.get("description", "")[:1500],
                "apply_url": j.get("redirect_url", "#"),
                "posted": created,
                "days_ago": freshness_score(created),
                "source": "Naukri/Adzuna",
            })
        log.info(f"Adzuna: {len(jobs)} jobs for '{keyword}' in '{location}'")
        return jobs
    except Exception as e:
        log.error(f"Adzuna error: {e}")
        return []


# ── Main entry ────────────────────────────────────────────────────────────
def fetch_all_jobs() -> list:
    keywords  = generate_keywords()
    locations = RESUME["ideal_job"]["locations"][:3]
    max_jobs  = int(os.getenv("MAX_JOBS_PER_RUN", "30"))

    seen_ids, all_jobs = set(), []

    for keyword in keywords[:3]:
        for location in locations[:2]:
            for job in fetch_linkedin(keyword.strip(), location.strip()):
                if job["id"] not in seen_ids:
                    seen_ids.add(job["id"])
                    all_jobs.append(job)
            time.sleep(0.3)
            for job in fetch_adzuna(keyword.strip(), location.strip()):
                if job["id"] not in seen_ids:
                    seen_ids.add(job["id"])
                    all_jobs.append(job)
            time.sleep(0.3)

    all_jobs.sort(key=lambda j: j.get("days_ago", 30))
    log.info(f"Total unique jobs: {len(all_jobs)} (LinkedIn + Adzuna, Capgemini excluded)")
    return all_jobs[:max_jobs]

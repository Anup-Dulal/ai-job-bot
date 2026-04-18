"""
naukri_fetcher.py — Multi-source job fetcher for LinkedIn, Naukri, Glassdoor, and Adzuna.

These adapters rely on public search endpoints and lightweight HTML parsing.
They are intentionally defensive and may need selector updates over time.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Callable, Iterable, List
from urllib.parse import quote_plus

import httpx

from llm_client import call_llm
from resume_profile import RESUME, get_resume_text

log = logging.getLogger("Fetcher")

EXCLUDE_COMPANIES = [company.lower() for company in RESUME["ideal_job"].get("avoid", [])]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
LINKEDIN_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
NAUKRI_URL = "https://www.naukri.com/{keyword}-jobs-in-{location}"
GLASSDOOR_URL = "https://www.glassdoor.co.in/Job/jobs.htm"


def _http_get(url: str, *, params: dict | None = None) -> str:
    for attempt in range(3):
        try:
            response = httpx.get(url, params=params, headers=HEADERS, timeout=20, follow_redirects=True)
            response.raise_for_status()
            return response.text
        except Exception as exc:
            wait = (attempt + 1) * 2
            log.warning("GET failed for %s (attempt %s): %s", url, attempt + 1, exc)
            time.sleep(wait)
    return ""


def generate_keywords() -> list[str]:
    configured = os.getenv("SEARCH_KEYWORDS", "").strip()
    if configured:
        separator = "|" if "|" in configured and "," not in configured else ","
        keywords = [item.strip() for item in configured.split(separator) if item.strip()]
        if keywords:
            return keywords[:4]

    prompt = f"""You are a job search expert. Based on this resume, generate exactly 4 targeted
job search keyword phrases optimized for finding Java backend jobs in India.
Mix role titles and skill combinations. 2-4 words max each.
Return ONLY a JSON array of 4 strings.

Resume:
{get_resume_text()}
"""
    result = call_llm(prompt, max_tokens=150)
    if result:
        try:
            start, end = result.find("["), result.rfind("]") + 1
            if start >= 0 and end > start:
                parsed = json.loads(result[start:end])
                if isinstance(parsed, list) and parsed:
                    return [str(item).strip() for item in parsed[:4] if str(item).strip()]
        except Exception as exc:
            log.warning("Keyword parse failed: %s", exc)
    return [
        "Java Backend Developer",
        "Spring Boot Developer",
        "Java Microservices Engineer",
        "Backend Engineer Java",
    ]


def freshness_score(posted_str: str) -> int:
    if not posted_str:
        return 30
    value = posted_str.lower()
    try:
        if "just now" in value or "today" in value:
            return 0
        match = re.search(r"(\d+)\s*(minute|hour|day|week|month)", value)
        if match:
            count = int(match.group(1))
            unit = match.group(2)
            if unit in {"minute", "hour"}:
                return 0
            if unit == "day":
                return count
            if unit == "week":
                return count * 7
            if unit == "month":
                return count * 30
        dt = datetime.fromisoformat(posted_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return 30


def is_excluded(company: str) -> bool:
    company_lc = company.lower()
    return any(item in company_lc for item in EXCLUDE_COMPANIES)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def fetch_linkedin(keyword: str, location: str) -> list[dict]:
    html = _http_get(
        LINKEDIN_URL,
        params={
            "keywords": keyword,
            "location": location,
            "geoId": "102713980",
            "f_TPR": "r604800",
            "position": 1,
            "pageNum": 0,
        },
    )
    if not html:
        return []

    job_ids = re.findall(r"urn:li:jobPosting:(\d+)", html)
    titles = re.findall(r"base-search-card__title[^>]*>\s*([^<]+)", html)
    companies = re.findall(r"base-search-card__subtitle[^>]*>.*?<a[^>]*>([^<]+)", html, re.DOTALL)
    locations = re.findall(r"job-search-card__location[^>]*>([^<]+)", html)
    posted = re.findall(r"job-search-card__listdate[^>]*>([^<]+)", html)
    jobs = []
    for idx, job_id in enumerate(job_ids[:10]):
        company = _clean(companies[idx]) if idx < len(companies) else ""
        if is_excluded(company):
            continue
        jobs.append(
            {
                "id": f"li_{job_id}",
                "title": _clean(titles[idx]) if idx < len(titles) else "",
                "company": company,
                "location": _clean(locations[idx]) if idx < len(locations) else location,
                "description": "",
                "apply_url": f"https://www.linkedin.com/jobs/view/{job_id}",
                "posted": _clean(posted[idx]) if idx < len(posted) else "",
                "days_ago": freshness_score(_clean(posted[idx]) if idx < len(posted) else ""),
                "source": "LinkedIn",
            }
        )
    return jobs


def fetch_naukri(keyword: str, location: str) -> list[dict]:
    keyword_slug = quote_plus(keyword.lower().replace(" ", "-"))
    location_slug = quote_plus(location.lower().replace(" ", "-"))
    html = _http_get(NAUKRI_URL.format(keyword=keyword_slug, location=location_slug))
    if not html:
        return []

    cards = re.findall(r'(<article[^>]+class="[^"]*jobTuple[^"]*"[\s\S]*?</article>)', html)
    jobs = []
    for idx, card in enumerate(cards[:10]):
        title_match = re.search(r'title="([^"]+)"', card)
        company_match = re.search(r'class="[^"]*comp-name[^"]*"[^>]*>\s*([^<]+)', card)
        link_match = re.search(r'href="([^"]+)"', card)
        location_match = re.search(r'class="[^"]*locWdth[^"]*"[^>]*>\s*([^<]+)', card)
        exp_match = re.search(r'class="[^"]*expwdth[^"]*"[^>]*>\s*([^<]+)', card)
        desc_match = re.search(r'class="[^"]*job-desc[^"]*"[^>]*>\s*([^<]+)', card)
        company = _clean(company_match.group(1) if company_match else "")
        if not company or is_excluded(company):
            continue
        jobs.append(
            {
                "id": f"naukri_{keyword_slug}_{location_slug}_{idx}",
                "title": _clean(title_match.group(1) if title_match else ""),
                "company": company,
                "location": _clean(location_match.group(1) if location_match else location),
                "description": _clean(desc_match.group(1) if desc_match else ""),
                "apply_url": link_match.group(1) if link_match else "",
                "posted": "",
                "days_ago": 3,
                "experience": _clean(exp_match.group(1) if exp_match else ""),
                "source": "Naukri",
            }
        )
    return jobs


def fetch_glassdoor(keyword: str, location: str) -> list[dict]:
    html = _http_get(
        GLASSDOOR_URL,
        params={"sc.keyword": keyword, "locT": "C", "locId": "", "locKeyword": location},
    )
    if not html:
        return []

    cards = re.findall(r'(<li[^>]+data-test="jobListing"[\s\S]*?</li>)', html)
    jobs = []
    for idx, card in enumerate(cards[:10]):
        title_match = re.search(r'data-test="job-title"[^>]*>\s*([^<]+)', card)
        company_match = re.search(r'data-test="employer-name"[^>]*>\s*([^<]+)', card)
        loc_match = re.search(r'data-test="emp-location"[^>]*>\s*([^<]+)', card)
        salary_match = re.search(r'data-test="detailSalary"[^>]*>\s*([^<]+)', card)
        link_match = re.search(r'href="([^"]+)"', card)
        company = _clean(company_match.group(1) if company_match else "")
        if not company or is_excluded(company):
            continue
        description = salary_match.group(1).strip() if salary_match else ""
        link = link_match.group(1) if link_match else ""
        if link and link.startswith("/"):
            link = "https://www.glassdoor.co.in" + link
        jobs.append(
            {
                "id": f"glassdoor_{quote_plus(keyword)}_{quote_plus(location)}_{idx}",
                "title": _clean(title_match.group(1) if title_match else ""),
                "company": company,
                "location": _clean(loc_match.group(1) if loc_match else location),
                "description": description,
                "apply_url": link,
                "posted": "",
                "days_ago": 4,
                "source": "Glassdoor",
            }
        )
    return jobs




def fetch_all_jobs() -> list[dict]:
    keywords = generate_keywords()
    locations = RESUME["ideal_job"]["locations"][:3]
    max_jobs = int(os.getenv("MAX_JOBS_PER_RUN", "50"))
    seen = set()
    all_jobs = []
    fetchers: Iterable[Callable[[str, str], List[dict]]] = (
        fetch_linkedin,
        fetch_naukri,
        fetch_glassdoor,
    )

    for keyword in keywords[:4]:
        for location in locations:
            for fetcher in fetchers:
                source_jobs = fetcher(keyword.strip(), location.strip())
                for job in source_jobs:
                    if not job.get("title") or not job.get("company"):
                        continue
                    if job["id"] in seen:
                        continue
                    seen.add(job["id"])
                    all_jobs.append(job)
                time.sleep(0.3)

    all_jobs.sort(key=lambda job: (job.get("days_ago", 30), job.get("source", ""), job.get("title", "")))
    log.info("Fetched %s raw jobs across LinkedIn, Naukri, and Glassdoor", len(all_jobs))
    return all_jobs[:max_jobs]

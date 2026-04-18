"""
naukri_fetcher.py — Multi-source job fetcher:
  - Naukri JSON API  → India jobs (priority)
  - LinkedIn         → India Easy Apply + Remote Easy Apply
  - Indeed           → Remote/overseas jobs (indeed.com with remotejob=1)

LinkedIn "Open website to apply" jobs are filtered out — only Easy Apply kept.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import List
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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

LINKEDIN_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LINKEDIN_JOB_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
NAUKRI_URL = "https://www.naukri.com/{keyword}-jobs-in-{location}"
INDEED_URL = "https://www.indeed.com/jobs"


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


def _is_easy_apply(job_id: str) -> bool:
    """Check if a LinkedIn job has Easy Apply (vs 'Apply on company website')."""
    try:
        html = _http_get(LINKEDIN_JOB_URL.format(job_id=job_id))
        if not html:
            return True  # assume easy apply if we can't check
        # Easy Apply shows a button with "Easy Apply" text
        # External apply shows "Apply" linking to company site
        if "easy apply" in html.lower():
            return True
        if "applymethod" in html.lower():
            # applyMethod: "ComplexOnsiteApply" = Easy Apply
            # applyMethod: "OffsiteApply" = external
            if "offsiteapply" in html.lower():
                return False
        return True  # default to include if uncertain
    except Exception:
        return True


def fetch_linkedin(keyword: str, location: str) -> list[dict]:
    """Fetch from LinkedIn — Easy Apply jobs only."""
    params: dict = {
        "keywords": keyword,
        "f_TPR": "r604800",  # last 7 days
        "f_LF": "f_AL",      # Easy Apply filter
        "position": 1,
        "pageNum": 0,
    }
    if location.lower() == "remote":
        params["f_WT"] = "2"  # remote work type
    else:
        params["location"] = location
        params["geoId"] = "102713980"  # India

    html = _http_get(LINKEDIN_URL, params=params)
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
                "easy_apply": True,  # f_LF=f_AL filter ensures these are Easy Apply
            }
        )
    return jobs


def fetch_indeed_remote(keyword: str) -> list[dict]:
    """Fetch remote/overseas jobs from Indeed global."""
    try:
        params = {
            "q": keyword,
            "l": "Remote",
            "remotejob": "1",
            "sort": "date",
            "fromage": "7",
        }
        resp = httpx.get(
            INDEED_URL,
            params=params,
            headers={
                **HEADERS,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=20,
            follow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text

        job_keys = re.findall(r'data-jk="([a-f0-9]+)"', html)
        titles = re.findall(r'class="jobTitle[^"]*"[^>]*>.*?<span[^>]*>([^<]+)</span>', html, re.DOTALL)
        companies = re.findall(r'data-testid="company-name"[^>]*>([^<]+)', html)
        locations_found = re.findall(r'data-testid="text-location"[^>]*>([^<]+)', html)
        snippets = re.findall(r'class="[^"]*job-snippet[^"]*"[^>]*>([\s\S]*?)</ul>', html)

        jobs = []
        for idx, job_key in enumerate(job_keys[:10]):
            company = _clean(companies[idx]) if idx < len(companies) else ""
            if not company or is_excluded(company):
                continue
            snippet_html = snippets[idx] if idx < len(snippets) else ""
            description = _clean(re.sub(r"<li>", " ", snippet_html))
            loc = _clean(locations_found[idx]) if idx < len(locations_found) else "Remote"
            jobs.append({
                "id": f"indeed_{job_key}",
                "title": _clean(titles[idx]) if idx < len(titles) else "",
                "company": company,
                "location": loc,
                "description": description,
                "apply_url": f"https://www.indeed.com/viewjob?jk={job_key}",
                "posted": "",
                "days_ago": 3,
                "source": "Indeed",
                "easy_apply": False,  # Indeed links to external apply
            })
        log.info("Indeed remote fetched %s jobs for %s", len(jobs), keyword)
        return jobs
    except Exception as exc:
        log.warning("Indeed remote fetch failed for %s: %s", keyword, exc)
        return []


def fetch_naukri(keyword: str, location: str) -> list[dict]:
    """Fetch from Naukri using HTML scraping with current selectors."""
    keyword_slug = keyword.lower().replace(" ", "-")
    location_slug = location.lower().replace(" ", "-")
    url = f"https://www.naukri.com/{quote_plus(keyword_slug)}-jobs-in-{quote_plus(location_slug)}"
    html = _http_get(url)
    if not html:
        return []

    jobs = []
    # Naukri embeds job data as JSON in a script tag
    json_match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', html, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            job_list = (
                data.get("jobsData", {}).get("jobDetails", [])
                or data.get("initialState", {}).get("jobsData", {}).get("jobDetails", [])
            )
            for idx, item in enumerate(job_list[:15]):
                company = item.get("companyName", "")
                if not company or is_excluded(company):
                    continue
                title = item.get("title", "")
                job_id = item.get("jobId", f"naukri_{idx}")
                loc_list = item.get("placeholders", [])
                location_str = next(
                    (p.get("label", "") for p in loc_list if p.get("type") == "location"),
                    location,
                )
                exp_str = next(
                    (p.get("label", "") for p in loc_list if p.get("type") == "experience"),
                    "",
                )
                description = item.get("jobDescription", "") or item.get("tagsAndSkills", "")
                if exp_str:
                    description = f"{description} Experience: {exp_str}".strip()
                apply_url = f"https://www.naukri.com{item.get('jdURL', '')}" if item.get("jdURL") else ""
                posted = item.get("footerPlaceholderLabel", "")
                jobs.append({
                    "id": f"naukri_{job_id}",
                    "title": title,
                    "company": company,
                    "location": location_str or location,
                    "description": _clean(description),
                    "apply_url": apply_url,
                    "posted": posted,
                    "days_ago": freshness_score(posted),
                    "source": "Naukri",
                    "easy_apply": True,
                })
            if jobs:
                log.info("Naukri JSON: %s jobs for %s/%s", len(jobs), keyword, location)
                return jobs
        except Exception as exc:
            log.warning("Naukri JSON parse failed for %s/%s: %s", keyword, location, exc)

    # Fallback: regex scraping on HTML
    # Try multiple card patterns Naukri has used
    cards = (
        re.findall(r'(<article[^>]+class="[^"]*jobTuple[^"]*"[\s\S]*?</article>)', html)
        or re.findall(r'(<div[^>]+class="[^"]*job-tuple[^"]*"[\s\S]*?</div>\s*</div>)', html)
    )
    for idx, card in enumerate(cards[:15]):
        title_match = re.search(r'(?:title|data-job-title)="([^"]+)"', card)
        company_match = re.search(r'class="[^"]*(?:comp-name|company-name)[^"]*"[^>]*>\s*([^<]+)', card)
        link_match = re.search(r'href="(https://www\.naukri\.com/job-listings[^"]+)"', card)
        location_match = re.search(r'class="[^"]*(?:locWdth|location)[^"]*"[^>]*>\s*([^<]+)', card)
        exp_match = re.search(r'class="[^"]*(?:expwdth|experience)[^"]*"[^>]*>\s*([^<]+)', card)
        desc_match = re.search(r'class="[^"]*(?:job-desc|description)[^"]*"[^>]*>\s*([^<]+)', card)
        company = _clean(company_match.group(1) if company_match else "")
        if not company or is_excluded(company):
            continue
        jobs.append({
            "id": f"naukri_{quote_plus(keyword_slug)}_{quote_plus(location_slug)}_{idx}",
            "title": _clean(title_match.group(1) if title_match else ""),
            "company": company,
            "location": _clean(location_match.group(1) if location_match else location),
            "description": _clean(desc_match.group(1) if desc_match else ""),
            "apply_url": link_match.group(1) if link_match else "",
            "posted": "",
            "days_ago": 3,
            "experience": _clean(exp_match.group(1) if exp_match else ""),
            "source": "Naukri",
            "easy_apply": True,
        })

    log.info("Naukri HTML: %s jobs for %s/%s", len(jobs), keyword, location)
    return jobs




def fetch_all_jobs() -> list[dict]:
    keywords = generate_keywords()
    india_locations = RESUME["ideal_job"]["locations"][:3]
    max_jobs = int(os.getenv("MAX_JOBS_PER_RUN", "50"))
    seen: set = set()
    all_jobs: list = []

    def _add_jobs(source_jobs: list) -> None:
        for job in source_jobs:
            if not job.get("title") or not job.get("company"):
                continue
            if job["id"] in seen:
                continue
            seen.add(job["id"])
            all_jobs.append(job)

    # India: Naukri first (best for India), then LinkedIn Easy Apply
    for keyword in keywords[:4]:
        for location in india_locations:
            _add_jobs(fetch_naukri(keyword.strip(), location.strip()))
            time.sleep(0.3)
            _add_jobs(fetch_linkedin(keyword.strip(), location.strip()))
            time.sleep(0.3)

    # Remote/worldwide: LinkedIn Easy Apply remote + Indeed global remote
    for keyword in keywords[:2]:
        _add_jobs(fetch_linkedin(keyword.strip(), "Remote"))
        time.sleep(0.3)
        _add_jobs(fetch_indeed_remote(keyword.strip()))
        time.sleep(0.3)

    all_jobs.sort(key=lambda job: (job.get("days_ago", 30), job.get("source", ""), job.get("title", "")))
    log.info(
        "Fetched %s jobs — Naukri (India) + LinkedIn Easy Apply (India+Remote) + Indeed (Remote overseas)",
        len(all_jobs),
    )
    return all_jobs[:max_jobs]

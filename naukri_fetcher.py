"""
job_fetcher.py — Multi-source job fetcher: LinkedIn + Naukri (via Indeed RSS)
Groq generates smart keywords from resume.
Filters: exclude Capgemini, sort by recency, no API keys needed.
"""

import os
import re
import time
import httpx
import logging
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from resume_profile import RESUME, get_resume_text
from llm_client import call_llm

log = logging.getLogger("JobFetcher")

EXCLUDE_COMPANIES = ["capgemini", "accenture body shop", "staffing", "recruitment", "placement"]

LINKEDIN_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
INDEED_RSS   = "https://in.indeed.com/rss"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ── Groq: generate smart keywords from resume ────────────────────────────
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


# ── Freshness score: newer = higher ──────────────────────────────────────
def freshness_score(posted_str: str) -> int:
    """Return days-ago as int. Lower = fresher. Default 30 if unknown."""
    if not posted_str:
        return 30
    posted_str = posted_str.lower()
    try:
        # LinkedIn: "2 days ago", "1 week ago", "just now"
        if "just now" in posted_str or "today" in posted_str:
            return 0
        m = re.search(r"(\d+)\s*(minute|hour|day|week|month)", posted_str)
        if m:
            n, unit = int(m.group(1)), m.group(2)
            if "minute" in unit or "hour" in unit: return 0
            if "day" in unit:   return n
            if "week" in unit:  return n * 7
            if "month" in unit: return n * 30
        # ISO date string
        dt = datetime.fromisoformat(posted_str.replace('Z', '+00:00'))
        return (datetime.now(timezone.utc) - dt).days
    except:
        return 30


# ── Filter: exclude unwanted companies ───────────────────────────────────
def is_excluded(company: str) -> bool:
    c = company.lower()
    return any(ex in c for ex in EXCLUDE_COMPANIES)


# ── LinkedIn fetcher ──────────────────────────────────────────────────────
def parse_linkedin_html(html: str) -> list:
    job_ids  = re.findall(r'urn:li:jobPosting:(\d+)', html)
    titles   = re.findall(r'base-search-card__title[^>]*>\s*([^<]+)', html)
    companies= re.findall(r'base-search-card__subtitle[^>]*>.*?<a[^>]*>([^<]+)', html, re.DOTALL)
    locations= re.findall(r'job-search-card__location[^>]*>([^<]+)', html)
    posted   = re.findall(r'job-search-card__listdate[^>]*>([^<]+)', html)

    jobs = []
    for i, job_id in enumerate(job_ids[:10]):
        title   = titles[i].strip()   if i < len(titles)    else ""
        company = companies[i].strip() if i < len(companies) else ""
        loc     = locations[i].strip() if i < len(locations) else ""
        post    = posted[i].strip()    if i < len(posted)    else ""
        if title and not is_excluded(company):
            jobs.append({
                "id": f"li_{job_id}",
                "title": title,
                "company": company,
                "location": loc,
                "description": f"{title} at {company} in {loc}",
                "apply_url": f"https://www.linkedin.com/jobs/view/{job_id}",
                "posted": post,
                "days_ago": freshness_score(post),
                "source": "LinkedIn",
            })
    return jobs


def fetch_linkedin(keyword: str, location: str = "India") -> list:
    params = {
        "keywords": keyword, "location": location,
        "geoId": "102713980", "f_TPR": "r604800",
        "f_E": "3,4", "position": 1, "pageNum": 0,
    }
    try:
        resp = httpx.get(LINKEDIN_URL, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        jobs = parse_linkedin_html(resp.text)
        log.info(f"LinkedIn: {len(jobs)} jobs for '{keyword}' in '{location}'")
        return jobs
    except Exception as e:
        log.error(f"LinkedIn error: {e}")
        return []


# ── Indeed RSS fetcher (covers Naukri-listed jobs too) ────────────────────
def fetch_indeed(keyword: str, location: str = "India") -> list:
    params = {"q": keyword, "l": location, "sort": "date", "fromage": "7", "limit": "15"}
    try:
        resp = httpx.get(INDEED_RSS, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        ns = {"dc": "http://purl.org/dc/elements/1.1/"}
        jobs = []
        for item in root.findall(".//item"):
            title   = (item.findtext("title") or "").strip()
            company = (item.findtext("dc:creator", namespaces=ns) or "").strip()
            loc     = (item.findtext("dc:subject", namespaces=ns) or location).strip()
            link    = (item.findtext("link") or "").strip()
            desc    = re.sub(r'<[^>]+>', '', item.findtext("description") or "").strip()
            pub     = (item.findtext("pubDate") or "").strip()
            job_id  = re.search(r'jk=([a-f0-9]+)', link)
            if title and not is_excluded(company):
                jobs.append({
                    "id": f"in_{job_id.group(1) if job_id else abs(hash(link))}",
                    "title": title,
                    "company": company,
                    "location": loc,
                    "description": desc[:1500],
                    "apply_url": link,
                    "posted": pub,
                    "days_ago": freshness_score(pub),
                    "source": "Indeed",
                })
        log.info(f"Indeed: {len(jobs)} jobs for '{keyword}' in '{location}'")
        return jobs
    except Exception as e:
        log.error(f"Indeed RSS error: {e}")
        return []


# ── Main entry ────────────────────────────────────────────────────────────
def fetch_all_jobs() -> list:
    keywords  = generate_keywords()
    locations = RESUME["ideal_job"]["locations"][:3]
    max_jobs  = int(os.getenv("MAX_JOBS_PER_RUN", "30"))

    seen_ids, all_jobs = set(), []

    for keyword in keywords[:3]:
        for location in locations[:2]:
            # LinkedIn
            for job in fetch_linkedin(keyword.strip(), location.strip()):
                if job["id"] not in seen_ids:
                    seen_ids.add(job["id"])
                    all_jobs.append(job)
            time.sleep(0.3)
            # Indeed (includes Naukri jobs)
            for job in fetch_indeed(keyword.strip(), location.strip()):
                if job["id"] not in seen_ids:
                    seen_ids.add(job["id"])
                    all_jobs.append(job)
            time.sleep(0.3)

    # Sort by freshness (newest first)
    all_jobs.sort(key=lambda j: j.get("days_ago", 30))

    log.info(f"Total unique jobs: {len(all_jobs)} (sorted by recency, Capgemini excluded)")
    return all_jobs[:max_jobs]

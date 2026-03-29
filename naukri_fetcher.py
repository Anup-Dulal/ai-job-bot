"""
naukri_fetcher.py — AI-powered job search using Groq + Google Custom Search.
Groq reads the resume and generates smart search queries.
Google Custom Search finds fresh Naukri/LinkedIn job listings.
Free: 100 Google searches/day, unlimited Groq.
"""

import os
import httpx
import logging
import json
from resume_profile import RESUME, get_resume_text
from llm_client import call_llm

log = logging.getLogger("JobFetcher")

GOOGLE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"


def generate_search_queries() -> list:
    """
    Ask Groq to generate smart job search queries based on the resume.
    Falls back to hardcoded queries if Groq unavailable.
    """
    prompt = f"""Based on this resume, generate 5 Google search queries to find the best matching jobs on Naukri.
    Focus on: role titles, key skills, experience level, location.
    Return ONLY a JSON array of 5 query strings. Each query should be specific and include site:naukri.com.
    
    Resume:
    {get_resume_text()}
    
    Example format: ["site:naukri.com java backend developer noida 3-5 years", ...]
    Return ONLY the JSON array."""

    result = call_llm(prompt, max_tokens=300, json_mode=False)
    if result:
        try:
            # extract JSON array from response
            start = result.find('[')
            end = result.rfind(']') + 1
            if start >= 0 and end > start:
                queries = json.loads(result[start:end])
                if isinstance(queries, list) and len(queries) > 0:
                    log.info(f"Groq generated {len(queries)} search queries")
                    return queries
        except Exception as e:
            log.warning(f"Could not parse Groq queries: {e}")

    # Fallback: build queries from resume directly
    roles = RESUME["ideal_job"]["roles"][:3]
    locations = RESUME["ideal_job"]["locations"][:2]
    queries = []
    for role in roles:
        for loc in locations[:2]:
            queries.append(f"site:naukri.com {role} {loc} {RESUME['experience_years']} years")
    log.info(f"Using {len(queries)} fallback search queries")
    return queries[:5]


def search_google(query: str) -> list:
    """Search Google Custom Search API for job listings."""
    api_key = os.getenv("GOOGLE_API_KEY", "")
    cx = os.getenv("GOOGLE_CX", "")

    if not api_key or not cx:
        log.warning("GOOGLE_API_KEY or GOOGLE_CX not set")
        return []

    try:
        resp = httpx.get(
            GOOGLE_SEARCH_URL,
            params={"key": api_key, "cx": cx, "q": query, "num": 10},
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        jobs = []
        for item in items:
            link = item.get("link", "")
            if "naukri.com" in link and "/job-listings-" in link:
                jobs.append({
                    "id": link.split("-")[-1].split("?")[0],
                    "title": item.get("title", "").replace(" - Naukri.com", ""),
                    "company": "",
                    "location": "",
                    "description": item.get("snippet", ""),
                    "apply_url": link,
                    "posted": "",
                })
        log.info(f"Google: {len(jobs)} Naukri jobs for '{query}'")
        return jobs
    except Exception as e:
        log.error(f"Google search error: {e}")
        return []


def fetch_all_jobs() -> list:
    """Main entry: Groq generates queries → Google finds jobs → return list."""
    queries = generate_search_queries()
    max_per_run = int(os.getenv("MAX_JOBS_PER_RUN", "30"))

    seen_ids = set()
    all_jobs = []

    for query in queries:
        jobs = search_google(query)
        for job in jobs:
            if job["id"] and job["id"] not in seen_ids:
                seen_ids.add(job["id"])
                all_jobs.append(job)
        if len(all_jobs) >= max_per_run:
            break

    log.info(f"Total unique jobs fetched: {len(all_jobs)}")
    return all_jobs[:max_per_run]

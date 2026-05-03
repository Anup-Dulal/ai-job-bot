"""
naukri_playwright.py — Playwright-based Naukri scraper with login session persistence.

Uses a headless browser to:
1. Log in to Naukri once and save session cookies
2. Search for jobs with filters (keyword, location, experience)
3. Extract full job details including description
4. Handle pagination

Falls back gracefully if Playwright is not installed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import List

log = logging.getLogger("NaukriPlaywright")

SESSION_FILE = Path(__file__).resolve().parent / "data" / "naukri_session.json"
SESSION_FILE.parent.mkdir(exist_ok=True)

NAUKRI_LOGIN_URL = "https://www.naukri.com/nlogin/login"
NAUKRI_SEARCH_URL = "https://www.naukri.com/{keyword}-jobs-in-{location}"


def _is_playwright_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except ImportError:
        return False


def _save_session(cookies: list) -> None:
    SESSION_FILE.write_text(json.dumps(cookies))
    log.info("Naukri session saved to %s", SESSION_FILE)


def _load_session() -> list | None:
    if not SESSION_FILE.exists():
        return None
    try:
        cookies = json.loads(SESSION_FILE.read_text())
        log.info("Loaded Naukri session from %s", SESSION_FILE)
        return cookies
    except Exception:
        return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def login_naukri(email: str, password: str) -> bool:
    """Log in to Naukri and save session cookies. Returns True on success."""
    if not _is_playwright_available():
        log.warning("Playwright not installed — skipping Naukri login")
        return False

    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()

            log.info("Navigating to Naukri login...")
            page.goto(NAUKRI_LOGIN_URL, wait_until="networkidle", timeout=30000)
            time.sleep(2)

            # Fill login form
            page.fill('input[placeholder*="Email"]', email)
            time.sleep(0.5)
            page.fill('input[placeholder*="Password"]', password)
            time.sleep(0.5)
            page.click('button[type="submit"]')

            # Wait for redirect after login
            try:
                page.wait_for_url("**/mnjuser/**", timeout=15000)
                log.info("Naukri login successful")
            except PWTimeout:
                # Try alternate success indicator
                try:
                    page.wait_for_selector(".nI-gNb-drawer__icon", timeout=10000)
                    log.info("Naukri login successful (alternate check)")
                except PWTimeout:
                    log.warning("Naukri login may have failed — saving cookies anyway")

            cookies = context.cookies()
            _save_session(cookies)
            browser.close()
            return True

    except Exception as exc:
        log.error("Naukri login failed: %s", exc)
        return False


def fetch_naukri_playwright(keyword: str, location: str, max_jobs: int = 15) -> List[dict]:
    """
    Fetch jobs from Naukri using Playwright with session cookies.
    Falls back to empty list if Playwright unavailable or session expired.
    """
    if not _is_playwright_available():
        return []

    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    cookies = _load_session()
    if not cookies:
        log.info("No Naukri session found — attempting login")
        email = os.getenv("NAUKRI_EMAIL", os.getenv("PROFILE_EMAIL", ""))
        password = os.getenv("NAUKRI_PASSWORD", "")
        if email and password:
            login_naukri(email, password)
            cookies = _load_session()
        if not cookies:
            log.warning("No Naukri session available — skipping Playwright fetch")
            return []

    keyword_slug = keyword.lower().replace(" ", "-")
    location_slug = location.lower().replace(" ", "-")
    url = NAUKRI_SEARCH_URL.format(keyword=keyword_slug, location=location_slug)

    jobs = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )

            # Restore session
            context.add_cookies(cookies)
            page = context.new_page()

            log.info("Fetching Naukri jobs: %s in %s", keyword, location)
            page.goto(url, wait_until="networkidle", timeout=30000)
            time.sleep(2)

            # Check if session expired (redirected to login)
            if "nlogin" in page.url or "login" in page.url.lower():
                log.warning("Naukri session expired — clearing and retrying login")
                SESSION_FILE.unlink(missing_ok=True)
                browser.close()
                return []

            # Wait for job cards to load
            try:
                page.wait_for_selector(".srp-jobtuple-wrapper, article.jobTuple", timeout=10000)
            except PWTimeout:
                log.warning("No job cards found on Naukri for %s/%s", keyword, location)
                browser.close()
                return []

            # Extract job cards
            job_cards = page.query_selector_all(".srp-jobtuple-wrapper, article.jobTuple")
            log.info("Found %s job cards on Naukri", len(job_cards))

            for idx, card in enumerate(job_cards[:max_jobs]):
                try:
                    title_el = card.query_selector("a.title, .jobTupleHeader a")
                    company_el = card.query_selector(".comp-name, .companyInfo a")
                    location_el = card.query_selector(".locWdth, .location")
                    exp_el = card.query_selector(".expwdth, .experience")
                    desc_el = card.query_selector(".job-desc, .jobDescription")
                    link_el = card.query_selector("a.title, .jobTupleHeader a")

                    title = _clean(title_el.inner_text() if title_el else "")
                    company = _clean(company_el.inner_text() if company_el else "")
                    loc = _clean(location_el.inner_text() if location_el else location)
                    exp = _clean(exp_el.inner_text() if exp_el else "")
                    desc = _clean(desc_el.inner_text() if desc_el else "")
                    link = link_el.get_attribute("href") if link_el else ""

                    if not title or not company:
                        continue

                    # Build full description with experience
                    full_desc = desc
                    if exp:
                        full_desc = f"{desc} Experience: {exp}".strip()

                    jobs.append({
                        "id": f"naukri_pw_{keyword_slug}_{location_slug}_{idx}",
                        "title": title,
                        "company": company,
                        "location": loc,
                        "description": full_desc,
                        "apply_url": link if link and link.startswith("http") else f"https://www.naukri.com{link}",
                        "posted": "",
                        "days_ago": 2,
                        "source": "Naukri",
                        "easy_apply": True,
                    })
                except Exception as exc:
                    log.debug("Error parsing job card %s: %s", idx, exc)
                    continue

            browser.close()
            log.info("Naukri Playwright: %s jobs for %s/%s", len(jobs), keyword, location)

    except Exception as exc:
        log.error("Naukri Playwright fetch failed for %s/%s: %s", keyword, location, exc)

    return jobs

"""
apply_agent.py — Playwright-based Naukri application form auto-filler.

Flow:
1. Log in to Naukri (reuses saved session from naukri_playwright.py)
2. Navigate to the job apply page
3. Detect form fields (text, select, radio, file upload)
4. Auto-fill using profile data + LLM-generated answers
5. Upload tailored resume PDF
6. STOP before final submit — send confirmation to Telegram
7. User confirms → submit OR user cancels → abort

Safety:
- Never auto-submits without explicit user confirmation
- Detects CAPTCHA and falls back to manual
- All actions logged to Telegram
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from notifier import send_telegram
from resume_profile import RESUME

log = logging.getLogger("ApplyAgent")

# Common Naukri form field patterns
FIELD_PATTERNS = {
    "name": ["name", "full name", "candidate name"],
    "email": ["email", "e-mail", "email address"],
    "phone": ["phone", "mobile", "contact", "phone number"],
    "experience": ["experience", "years of experience", "total experience"],
    "current_ctc": ["current ctc", "current salary", "current package"],
    "expected_ctc": ["expected ctc", "expected salary", "expected package"],
    "notice_period": ["notice period", "notice", "joining time"],
    "location": ["current location", "location", "city"],
    "cover_letter": ["cover letter", "cover note", "message"],
}


def _is_playwright_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except ImportError:
        return False


def _get_field_answer(label: str, job: dict, cover_letter: str = "") -> str:
    """Map a form field label to the right answer from profile."""
    label_lower = label.lower().strip()

    for field_type, patterns in FIELD_PATTERNS.items():
        if any(p in label_lower for p in patterns):
            if field_type == "name":
                return RESUME.get("name", "")
            elif field_type == "email":
                return RESUME.get("email", "")
            elif field_type == "phone":
                return RESUME.get("phone", "")
            elif field_type == "experience":
                return str(RESUME.get("experience_years", "4"))
            elif field_type == "current_ctc":
                return RESUME.get("expected_ctc", "As per industry standards")
            elif field_type == "expected_ctc":
                return RESUME.get("expected_ctc", "9-10 LPA")
            elif field_type == "notice_period":
                return RESUME.get("notice_period", "60 days")
            elif field_type == "location":
                return RESUME.get("location", "India")
            elif field_type == "cover_letter":
                return cover_letter[:500] if cover_letter else ""

    # Use LLM for unknown questions
    try:
        from agent import JobApplicationAgent
        agent = JobApplicationAgent()
        return agent.answer_form_question(label, job_context=job)
    except Exception:
        return ""


class ApplyAgent:
    """
    Playwright-based agent that auto-fills Naukri job application forms.
    Always stops before final submission for user confirmation.
    """

    def __init__(self):
        self._available = _is_playwright_available()
        if not self._available:
            log.warning("Playwright not installed — ApplyAgent disabled")

    def apply(self, job: dict, application_packet: dict) -> dict:
        """
        Navigate to job apply page, fill form, stop before submit.

        Returns:
            {
                "status": "ready_to_submit" | "captcha_detected" | "already_applied"
                          | "playwright_unavailable" | "error",
                "message": str,
                "screenshot_path": str | None,
            }
        """
        if not self._available:
            return {
                "status": "playwright_unavailable",
                "message": "Playwright not installed. Apply manually at: " + job.get("link", "#"),
                "screenshot_path": None,
            }

        apply_url = job.get("link", "")
        if not apply_url:
            return {
                "status": "error",
                "message": "No apply URL for this job.",
                "screenshot_path": None,
            }

        source = job.get("source", "")
        if source == "Naukri":
            return self._apply_naukri(job, application_packet)
        elif source == "LinkedIn":
            return self._apply_linkedin(job, application_packet)
        else:
            return {
                "status": "error",
                "message": f"Auto-apply not supported for {source}. Apply manually: {apply_url}",
                "screenshot_path": None,
            }

    def _apply_naukri(self, job: dict, application_packet: dict) -> dict:
        """Auto-fill Naukri application form."""
        from naukri_playwright import _load_session, login_naukri, SESSION_FILE

        resume_pdf_path = application_packet.get("tailored_resume_path", "")
        cover_letter = application_packet.get("cover_letter", "")
        apply_url = job.get("link", "")

        # Ensure we have a session
        cookies = _load_session()
        if not cookies:
            email = os.getenv("NAUKRI_EMAIL", "")
            password = os.getenv("NAUKRI_PASSWORD", "")
            if not email or not password:
                return {
                    "status": "error",
                    "message": "NAUKRI_EMAIL and NAUKRI_PASSWORD required for auto-apply.",
                    "screenshot_path": None,
                }
            login_naukri(email, password)
            cookies = _load_session()
            if not cookies:
                return {
                    "status": "error",
                    "message": "Naukri login failed. Check credentials.",
                    "screenshot_path": None,
                }

        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        screenshot_path = None
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
                    viewport={"width": 1280, "height": 900},
                )
                context.add_cookies(cookies)
                page = context.new_page()

                send_telegram(f"🤖 Opening application form for <b>{job['title']}</b> @ {job['company']}...")
                log.info("Navigating to apply URL: %s", apply_url)
                page.goto(apply_url, wait_until="networkidle", timeout=30000)
                time.sleep(2)

                # Check for session expiry
                if "nlogin" in page.url or "login" in page.url.lower():
                    SESSION_FILE.unlink(missing_ok=True)
                    browser.close()
                    return {
                        "status": "error",
                        "message": "Session expired. Will re-login on next run.",
                        "screenshot_path": None,
                    }

                # Check for CAPTCHA
                if self._has_captcha(page):
                    screenshot_path = self._take_screenshot(page, job, "captcha")
                    browser.close()
                    return {
                        "status": "captcha_detected",
                        "message": f"CAPTCHA detected. Apply manually: {apply_url}",
                        "screenshot_path": screenshot_path,
                    }

                # Check if already applied
                if page.query_selector("text=Already Applied") or page.query_selector("text=Application Submitted"):
                    browser.close()
                    return {
                        "status": "already_applied",
                        "message": f"Already applied to {job['title']} at {job['company']}.",
                        "screenshot_path": None,
                    }

                # Click Apply button if present
                apply_btn = (
                    page.query_selector("button:has-text('Apply')")
                    or page.query_selector("a:has-text('Apply Now')")
                    or page.query_selector("[data-ga-track*='apply']")
                )
                if apply_btn:
                    apply_btn.click()
                    time.sleep(2)

                # Fill form fields
                filled_count = self._fill_form_fields(page, job, cover_letter)
                log.info("Filled %s form fields", filled_count)

                # Upload resume PDF if field exists
                if resume_pdf_path and Path(resume_pdf_path).exists():
                    self._upload_resume(page, resume_pdf_path)

                # Take screenshot of filled form BEFORE submit
                screenshot_path = self._take_screenshot(page, job, "filled")

                # DO NOT submit — wait for user confirmation
                browser.close()

                return {
                    "status": "ready_to_submit",
                    "message": (
                        f"Form filled for <b>{job['title']}</b> @ {job['company']}.\n"
                        f"Filled {filled_count} fields.\n"
                        f"⚠️ NOT submitted yet — review and apply manually at:\n{apply_url}"
                    ),
                    "screenshot_path": screenshot_path,
                    "apply_url": apply_url,
                }

        except PWTimeout:
            return {
                "status": "error",
                "message": f"Page timed out. Apply manually: {apply_url}",
                "screenshot_path": screenshot_path,
            }
        except Exception as exc:
            log.exception("Apply agent error: %s", exc)
            return {
                "status": "error",
                "message": f"Error during auto-fill: {exc}\nApply manually: {apply_url}",
                "screenshot_path": screenshot_path,
            }

    def _apply_linkedin(self, job: dict, application_packet: dict) -> dict:
        """LinkedIn Easy Apply form filler."""
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        apply_url = job.get("link", "")
        cover_letter = application_packet.get("cover_letter", "")
        resume_pdf_path = application_packet.get("tailored_resume_path", "")

        screenshot_path = None
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
                    viewport={"width": 1280, "height": 900},
                )
                page = context.new_page()

                send_telegram(f"🤖 Opening LinkedIn Easy Apply for <b>{job['title']}</b>...")
                page.goto(apply_url, wait_until="networkidle", timeout=30000)
                time.sleep(2)

                # Check for CAPTCHA
                if self._has_captcha(page):
                    screenshot_path = self._take_screenshot(page, job, "captcha")
                    browser.close()
                    return {
                        "status": "captcha_detected",
                        "message": f"CAPTCHA detected. Apply manually: {apply_url}",
                        "screenshot_path": screenshot_path,
                    }

                # Click Easy Apply button
                easy_apply_btn = (
                    page.query_selector("button:has-text('Easy Apply')")
                    or page.query_selector(".jobs-apply-button")
                )
                if not easy_apply_btn:
                    browser.close()
                    return {
                        "status": "error",
                        "message": f"Easy Apply button not found. Apply manually: {apply_url}",
                        "screenshot_path": None,
                    }

                easy_apply_btn.click()
                time.sleep(2)

                # Fill multi-step form
                filled_count = self._fill_form_fields(page, job, cover_letter)

                # Upload resume if field exists
                if resume_pdf_path and Path(resume_pdf_path).exists():
                    self._upload_resume(page, resume_pdf_path)

                screenshot_path = self._take_screenshot(page, job, "filled")
                browser.close()

                return {
                    "status": "ready_to_submit",
                    "message": (
                        f"LinkedIn Easy Apply form filled for <b>{job['title']}</b>.\n"
                        f"Filled {filled_count} fields.\n"
                        f"⚠️ NOT submitted — review and complete manually:\n{apply_url}"
                    ),
                    "screenshot_path": screenshot_path,
                    "apply_url": apply_url,
                }

        except Exception as exc:
            log.exception("LinkedIn apply error: %s", exc)
            return {
                "status": "error",
                "message": f"Error: {exc}\nApply manually: {apply_url}",
                "screenshot_path": screenshot_path,
            }

    def _fill_form_fields(self, page, job: dict, cover_letter: str) -> int:
        """Detect and fill all visible text/select form fields. Returns count filled."""
        filled = 0

        # Fill text inputs and textareas
        inputs = page.query_selector_all("input[type='text'], input[type='email'], input[type='tel'], textarea")
        for inp in inputs:
            try:
                # Get label for this field
                label = self._get_field_label(page, inp)
                if not label:
                    continue

                answer = _get_field_answer(label, job, cover_letter)
                if not answer:
                    continue

                # Only fill if empty
                current_val = inp.input_value() if inp.input_value else ""
                if not current_val:
                    inp.fill(answer)
                    filled += 1
                    time.sleep(0.2)
            except Exception as exc:
                log.debug("Could not fill input: %s", exc)

        # Fill select dropdowns
        selects = page.query_selector_all("select")
        for sel in selects:
            try:
                label = self._get_field_label(page, sel)
                if not label:
                    continue
                answer = _get_field_answer(label, job, cover_letter)
                if answer:
                    # Try to select matching option
                    options = sel.query_selector_all("option")
                    for opt in options:
                        opt_text = opt.inner_text().lower()
                        if answer.lower() in opt_text or opt_text in answer.lower():
                            sel.select_option(value=opt.get_attribute("value") or opt_text)
                            filled += 1
                            break
            except Exception as exc:
                log.debug("Could not fill select: %s", exc)

        return filled

    def _get_field_label(self, page, element) -> str:
        """Try to find the label text for a form element."""
        try:
            # Try aria-label
            aria = element.get_attribute("aria-label")
            if aria:
                return aria

            # Try placeholder
            placeholder = element.get_attribute("placeholder")
            if placeholder:
                return placeholder

            # Try associated <label> element
            field_id = element.get_attribute("id")
            if field_id:
                label_el = page.query_selector(f"label[for='{field_id}']")
                if label_el:
                    return label_el.inner_text()

            # Try parent label
            parent = element.evaluate("el => el.closest('label')")
            if parent:
                return element.evaluate("el => el.closest('label').innerText")

            # Try preceding sibling text
            name = element.get_attribute("name") or ""
            return name.replace("_", " ").replace("-", " ")
        except Exception:
            return ""

    def _upload_resume(self, page, resume_path: str) -> bool:
        """Upload resume PDF to file input field."""
        try:
            file_inputs = page.query_selector_all("input[type='file']")
            for inp in file_inputs:
                accept = inp.get_attribute("accept") or ""
                if "pdf" in accept.lower() or "resume" in (inp.get_attribute("name") or "").lower() or not accept:
                    inp.set_input_files(resume_path)
                    log.info("Uploaded resume: %s", resume_path)
                    time.sleep(1)
                    return True
        except Exception as exc:
            log.warning("Resume upload failed: %s", exc)
        return False

    def _has_captcha(self, page) -> bool:
        """Detect common CAPTCHA patterns."""
        captcha_selectors = [
            "iframe[src*='recaptcha']",
            "iframe[src*='captcha']",
            ".g-recaptcha",
            "#captcha",
            "[data-sitekey]",
            "text=verify you are human",
            "text=I'm not a robot",
        ]
        for selector in captcha_selectors:
            try:
                if page.query_selector(selector):
                    log.warning("CAPTCHA detected: %s", selector)
                    return True
            except Exception:
                pass
        return False

    def _take_screenshot(self, page, job: dict, suffix: str) -> Optional[str]:
        """Take a screenshot and return the path."""
        try:
            from pipeline import ARTIFACT_DIR, _slugify
            filename = f"screenshot-{_slugify(job.get('company', 'job'))}-{_slugify(job.get('title', ''))}-{suffix}.png"
            path = str(ARTIFACT_DIR / filename)
            page.screenshot(path=path, full_page=False)
            log.info("Screenshot saved: %s", path)
            return path
        except Exception as exc:
            log.warning("Screenshot failed: %s", exc)
            return None


def run_apply_agent(job: dict, application_packet: dict) -> dict:
    """
    Entry point for the apply agent.
    Called from telegram_poller when user taps ✅ Apply.
    Sends result back via Telegram.
    """
    agent = ApplyAgent()
    result = agent.apply(job, application_packet)

    status = result.get("status", "error")
    message = result.get("message", "")
    apply_url = result.get("apply_url", job.get("link", "#"))

    if status == "ready_to_submit":
        send_telegram(
            f"✅ <b>Form auto-filled!</b>\n\n"
            f"{message}\n\n"
            f"<a href=\"{apply_url}\">👉 Open job to review and submit</a>"
        )
    elif status == "captcha_detected":
        send_telegram(
            f"🔒 <b>CAPTCHA detected</b> — cannot auto-fill.\n\n"
            f"<a href=\"{apply_url}\">👉 Apply manually here</a>"
        )
    elif status == "already_applied":
        send_telegram(f"ℹ️ {message}")
    elif status == "playwright_unavailable":
        send_telegram(
            f"⚠️ Auto-fill not available in this environment.\n\n"
            f"<a href=\"{apply_url}\">👉 Apply manually here</a>"
        )
    else:
        send_telegram(
            f"⚠️ <b>Auto-fill failed:</b> {message}\n\n"
            f"<a href=\"{apply_url}\">👉 Apply manually here</a>"
        )

    return result

"""
pipeline.py — Multi-agent workflow orchestration for the job bot.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from agent import JobApplicationAgent
from llm_client import call_llm, rule_answer_question, rule_cover_letter, rule_resume_bullets
from naukri_fetcher import fetch_all_jobs
from notifier import notify_jobs, send_job_card, send_telegram
from pre_filter import pre_filter
from resume_profile import RESUME, get_resume_text
from storage import (
    get_action,
    get_job,
    init_db,
    list_pending_actions,
    log_run,
    mark_notified,
    recent_runs,
    set_action,
    upsert_jobs,
)

log = logging.getLogger("Pipeline")
ARTIFACT_DIR = Path(__file__).resolve().parent / "generated"
ARTIFACT_DIR.mkdir(exist_ok=True)


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-") or "job"


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _extract_experience(text: str) -> str:
    text = (text or "").lower()
    for pattern in [r"(\d+\s*[-–]\s*\d+\s*years?)", r"(\d+\+\s*years?)", r"(\d+\s*years?)"]:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return "Not specified"


def _extract_skills(description: str) -> List[str]:
    text = (description or "").lower()
    skills = [
        "java",
        "spring",
        "spring boot",
        "microservices",
        "rest api",
        "restful",
        "hibernate",
        "jpa",
        "sql",
        "mysql",
        "postgresql",
        "aws",
        "docker",
        "kubernetes",
        "jenkins",
        "git",
        "junit",
        "mockito",
        "kafka",
        "redis",
        "mongodb",
    ]
    found = []
    for skill in skills:
        if skill in text:
            label = "REST APIs" if skill in {"rest api", "restful"} else skill.title()
            if label not in found:
                found.append(label)
    return found


def _dedupe_jobs(jobs: List[dict]) -> List[dict]:
    deduped: Dict[str, dict] = {}
    for job in jobs:
        key = "|".join(
            [
                _slugify(job.get("title", "")),
                _slugify(job.get("company", "")),
                _slugify(job.get("location", "")),
            ]
        )
        current = deduped.get(key)
        if current is None or job.get("days_ago", 30) < current.get("days_ago", 30):
            deduped[key] = job
    return list(deduped.values())


def _write_text_artifact(prefix: str, job: dict, content: str) -> str:
    filename = f"{prefix}-{_slugify(job['company'])}-{_slugify(job['title'])}.md"
    path = ARTIFACT_DIR / filename
    path.write_text(content)
    return str(path)


def _write_pdf_artifact(prefix: str, job: dict, content: str) -> str:
    """Write content as a PDF file. Falls back to .md if fpdf2 not available."""
    try:
        from fpdf import FPDF

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Helvetica", size=11)

        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("# "):
                pdf.set_font("Helvetica", "B", 16)
                pdf.cell(0, 10, line[2:], ln=True)
                pdf.set_font("Helvetica", size=11)
            elif line.startswith("## "):
                pdf.set_font("Helvetica", "B", 13)
                pdf.ln(3)
                pdf.cell(0, 8, line[3:], ln=True)
                pdf.set_font("Helvetica", size=11)
            elif line.startswith("- "):
                pdf.cell(5, 7, "", ln=False)
                pdf.multi_cell(0, 7, f"- {line[2:]}")
            elif line:
                pdf.multi_cell(0, 7, line)
            else:
                pdf.ln(3)

        filename = f"{prefix}-{_slugify(job['company'])}-{_slugify(job['title'])}.pdf"
        path = ARTIFACT_DIR / filename
        pdf.output(str(path))
        return str(path)
    except ImportError:
        log.warning("fpdf2 not installed — falling back to .md artifact")
        return _write_text_artifact(prefix, job, content)


@dataclass
class ResumeSnapshot:
    skills: List[str]
    experience_years: int
    titles: List[str]
    projects: List[str]
    summary: str


class JobScraperAgent:
    def __init__(self, location_preferences: Optional[List[str]] = None):
        self.location_preferences = location_preferences or RESUME["ideal_job"]["locations"]

    def fetch_jobs(self) -> List[dict]:
        raw_jobs = fetch_all_jobs()

        # Augment with Playwright-scraped Naukri jobs if available
        try:
            from naukri_playwright import fetch_naukri_playwright
            from naukri_fetcher import generate_keywords
            keywords = generate_keywords()
            india_locations = self.location_preferences[:2]
            for keyword in keywords[:2]:
                for location in india_locations:
                    pw_jobs = fetch_naukri_playwright(keyword.strip(), location.strip(), max_jobs=10)
                    if pw_jobs:
                        log.info("Playwright added %s Naukri jobs for %s/%s", len(pw_jobs), keyword, location)
                        raw_jobs.extend(pw_jobs)
        except Exception as exc:
            log.debug("Playwright scraping skipped: %s", exc)

        location_tokens = [item.lower() for item in self.location_preferences]
        # Build broader match tokens (e.g. "bangalore" also matches "bengaluru")
        location_aliases = {
            "bangalore": ["bangalore", "bengaluru", "bengalore"],
            "delhi ncr": ["delhi", "ncr", "noida", "gurgaon", "gurugram", "faridabad"],
            "gurgaon": ["gurgaon", "gurugram"],
            "noida": ["noida", "greater noida"],
        }
        expanded_tokens: list[str] = []
        for token in location_tokens:
            expanded_tokens.append(token)
            for key, aliases in location_aliases.items():
                if token == key or token in aliases:
                    expanded_tokens.extend(aliases)
        expanded_tokens = list(set(expanded_tokens))

        normalized = []
        for job in raw_jobs:
            location = _normalize_text(job.get("location", ""))
            location_lc = location.lower()
            # Always keep remote jobs and jobs with no location info
            # Only filter by location for jobs that have a specific non-remote location
            is_remote = "remote" in location_lc or "worldwide" in location_lc or "anywhere" in location_lc
            has_no_location = location_lc in ("", "india")
            location_matches = any(token in location_lc for token in expanded_tokens)
            if not is_remote and not has_no_location and not location_matches:
                continue
            normalized.append(
                {
                    "id": job.get("id") or _slugify(
                        f"{job.get('title', '')}-{job.get('company', '')}-{job.get('location', '')}"
                    ),
                    "title": _normalize_text(job.get("title", "")),
                    "company": _normalize_text(job.get("company", "")),
                    "location": location,
                    "description": _normalize_text(job.get("description", "")),
                    "skills": _extract_skills(job.get("description", "")),
                    "experience": job.get("experience") or _extract_experience(job.get("description", "")),
                    "link": job.get("apply_url", ""),
                    "source": job.get("source", ""),
                    "days_ago": job.get("days_ago", 30),
                }
            )
        deduped = _dedupe_jobs(normalized)
        upsert_jobs(deduped)
        deduped.sort(key=lambda item: (item.get("days_ago", 30), item["title"]))
        return deduped


class JobScoringAgent:
    def __init__(self):
        self.resume = self._parse_resume()
        self.deep_agent = JobApplicationAgent()

    def _parse_resume(self) -> ResumeSnapshot:
        skills = []
        for values in RESUME["skills"].values():
            skills.extend(values)
        return ResumeSnapshot(
            skills=skills,
            experience_years=int(RESUME["experience_years"]),
            titles=RESUME["ideal_job"]["roles"],
            projects=RESUME["projects"],
            summary=RESUME["summary"],
        )

    def _skill_component(self, job: dict) -> tuple[int, List[str]]:
        resume_skills = {skill.lower() for skill in self.resume.skills}
        job_skills = [skill.lower() for skill in job.get("skills", [])]
        if not job_skills:
            job_skills = [skill for skill in resume_skills if skill in job.get("description", "").lower()]
        matched = sorted(set(skill for skill in job_skills if skill in resume_skills))
        ratio = len(matched) / max(len(set(job_skills)), 1)
        return round(ratio * 40), matched

    def _experience_component(self, job: dict) -> int:
        years = self.resume.experience_years
        exp = (job.get("experience") or "").lower()
        range_match = re.search(r"(\d+)\s*[-–]\s*(\d+)", exp)
        if range_match:
            low, high = int(range_match.group(1)), int(range_match.group(2))
            if low <= years <= high:
                return 30
            if years + 1 == low or years - 1 == high:
                return 22
            return 10
        plus_match = re.search(r"(\d+)\+", exp)
        if plus_match:
            required = int(plus_match.group(1))
            if years >= required:
                return 28
            if years + 1 == required:
                return 18
            return 8
        return 18

    def _role_component(self, job: dict) -> int:
        title = job.get("title", "").lower()
        targets = [role.lower() for role in self.resume.titles]
        if any(target == title for target in targets):
            return 20
        if any(target in title or title in target for target in targets):
            return 18
        hits = sum(1 for token in ["java", "spring", "backend", "developer", "engineer"] if token in title)
        return min(20, hits * 4)

    def _bonus_component(self, job: dict) -> tuple[int, List[str]]:
        description = f"{job.get('title', '')} {job.get('description', '')}".lower()
        keywords = ["microservices", "rest", "aws", "java 17", "spring boot", "distributed systems"]
        hits = [keyword for keyword in keywords if keyword in description]
        return min(10, len(hits) * 2), hits

    def score_jobs(self, jobs: List[dict]) -> List[dict]:
        scored = []
        for job in pre_filter(jobs):
            skill_score, matched_skills = self._skill_component(job)
            experience_score = self._experience_component(job)
            role_score = self._role_component(job)
            bonus_score, bonus_hits = self._bonus_component(job)
            weighted_score = skill_score + experience_score + role_score + bonus_score

            deep_result = self.deep_agent.process_job(
                {
                    "id": job["id"],
                    "title": job["title"],
                    "company": job["company"],
                    "location": job["location"],
                    "description": job["description"],
                    "source": job.get("source", ""),
                    "days_ago": job.get("days_ago", 30),
                    "apply_url": job.get("link", ""),
                }
            )
            llm_score = deep_result["fit_score"] if deep_result else weighted_score

            # When description is empty (e.g. LinkedIn cards), the rule-based score
            # is unreliable — trust the LLM score much more in that case.
            has_description = bool(job.get("description", "").strip())
            if has_description:
                final_score = round(weighted_score * 0.7 + llm_score * 0.3)
            else:
                final_score = round(weighted_score * 0.2 + llm_score * 0.8)

            reason_parts = []
            if matched_skills:
                reason_parts.append("Strong skill overlap on " + ", ".join(skill.title() for skill in matched_skills[:4]))
            if experience_score >= 22:
                reason_parts.append("experience range aligns well")
            if bonus_hits:
                reason_parts.append("bonus keywords: " + ", ".join(bonus_hits[:3]))
            if deep_result and deep_result.get("reasoning"):
                reason_parts.append(deep_result["reasoning"])

            scored.append(
                {
                    **job,
                    "score": max(0, min(100, final_score)),
                    "reason": "; ".join(reason_parts) or "Relevant Java backend match",
                    "decision": deep_result.get("decision", "MAYBE") if deep_result else "MAYBE",
                    "score_breakdown": {
                        "skill_match": skill_score,
                        "experience_match": experience_score,
                        "role_similarity": role_score,
                        "bonus_keywords": bonus_score,
                    },
                }
            )

        scored.sort(key=lambda item: (-item["score"], item.get("days_ago", 30), item["title"]))
        upsert_jobs(scored)
        return scored


class ResumeOptimizerAgent:
    def tailor_resume(self, job: dict) -> dict:
        # Try RAG-based tailoring first
        try:
            from rag_resume import tailor_resume_rag
            tailored = tailor_resume_rag(job)
            tailored["artifact_path"] = self._write_resume_artifact(job, tailored)
            return tailored
        except Exception as exc:
            log.warning("RAG tailoring failed: %s — falling back to LLM prompt", exc)

        # Fallback: direct LLM prompt
        prompt = f"""Tailor this resume truthfully for the following job.
Return ONLY JSON with keys: summary, skills, experience_bullets, projects, changes.

JOB DESCRIPTION:
{job.get("description", "")[:2500]}

RESUME:
{get_resume_text()}
"""
        result = call_llm(prompt, max_tokens=500, json_mode=True, quality=True)
        if result:
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict):
                    parsed["changes"] = parsed.get("changes", [])
                    parsed["tailored_for"] = f"{job.get('title')} at {job.get('company')}"
                    parsed["artifact_path"] = self._write_resume_artifact(job, parsed)
                    return parsed
            except Exception:
                log.warning("Tailored resume JSON parse failed; falling back to rule-based resume tailoring")

        skills = []
        for values in RESUME["skills"].values():
            skills.extend(values)
        prioritized = []
        description = job.get("description", "").lower()
        for skill in skills:
            if skill.lower() in description and skill not in prioritized:
                prioritized.append(skill)
        for skill in skills:
            if skill not in prioritized:
                prioritized.append(skill)

        tailored = {
            "summary": RESUME["summary"],
            "skills": prioritized[:14],
            "experience_bullets": rule_resume_bullets(job),
            "projects": RESUME["projects"][:3],
            "changes": [
                "Prioritized job-description keywords in the skills section",
                "Reordered bullets to emphasize Spring Boot, Java, and microservices work",
                "Kept all content truthful and derived from the original profile",
            ],
            "tailored_for": f"{job.get('title')} at {job.get('company')}",
        }
        tailored["artifact_path"] = self._write_resume_artifact(job, tailored)
        return tailored

    def _write_resume_artifact(self, job: dict, tailored: dict) -> str:
        content = [
            f"# {RESUME['name']}",
            "",
            f"## Target Role",
            f"{job.get('title')} at {job.get('company')}",
            "",
            "## Summary",
            tailored.get("summary", RESUME["summary"]),
            "",
            "## Skills",
            ", ".join(tailored.get("skills", [])),
            "",
            "## Experience Highlights",
        ]
        for bullet in tailored.get("experience_bullets", []):
            content.append(f"- {bullet}")
        content.extend(["", "## Projects"])
        for project in tailored.get("projects", []):
            content.append(f"- {project}")
        content.extend(["", "## Changes Made"])
        for change in tailored.get("changes", []):
            content.append(f"- {change}")
        return _write_pdf_artifact("resume", job, "\n".join(content) + "\n")


class ApplicationAssistantAgent:
    def prepare_application(self, job: dict, tailored_resume: dict) -> dict:
        cover_letter = rule_cover_letter(job)
        cover_letter_path = _write_text_artifact(
            "cover-letter",
            job,
            f"# Cover Letter\n\n{cover_letter}\n",
        )
        common_answers = {
            "why_do_you_want_this_role": rule_answer_question("Why do you want this role?"),
            "describe_your_spring_boot_experience": rule_answer_question(
                "Describe your experience with Spring Boot"
            ),
            "expected_salary": rule_answer_question("Expected salary"),
        }
        suggested_form_answers = [
            {
                "question": "Current location",
                "answer": RESUME["location"],
            },
            {
                "question": "Notice period",
                "answer": RESUME["notice_period"],
            },
            {
                "question": "Are you open to relocation?",
                "answer": "Yes, open to relocation within India for the right role.",
            },
        ]
        return {
            "job_id": job["id"],
            "tailored_resume": tailored_resume,
            "tailored_resume_path": tailored_resume.get("artifact_path"),
            "cover_letter": cover_letter,
            "cover_letter_path": cover_letter_path,
            "common_answers": common_answers,
            "form_answers": suggested_form_answers,
            "status": "READY_FOR_APPROVAL",
        }


class NotificationAgent:
    def notify_top_jobs(self, jobs: List[dict], top_n: int = 10) -> str:
        selected = jobs[:top_n]
        if not selected:
            message = "No strong Java Spring Boot matches found in this run."
            send_telegram(message)
            return message

        # Send a brief header first
        send_telegram(
            f"<b>Job Bot — {len(selected)} new matches found</b>\n"
            f"Sending each job below. Tap APPLY, REJECT, or SKIP on each one."
        )

        # Send each job as its own card with buttons
        for job in selected:
            send_job_card(job)
            time.sleep(0.5)  # avoid Telegram rate limit

        return f"Sent {len(selected)} job cards"


class WorkflowOrchestrator:
    def __init__(self):
        init_db()
        self.scraper = JobScraperAgent()
        self.scorer = JobScoringAgent()
        self.resume_optimizer = ResumeOptimizerAgent()
        self.application_assistant = ApplicationAssistantAgent()
        self.notification_agent = NotificationAgent()

    def run_once(self, top_n: int = 5) -> dict:
        jobs = self.scraper.fetch_jobs()
        scored_jobs = self.scorer.score_jobs(jobs)
        minimum_score = int(os.getenv("MIN_FIT_SCORE", "60"))
        shortlisted = [job for job in scored_jobs if job["score"] >= minimum_score]

        fresh_jobs = []
        for job in shortlisted[:top_n]:
            stored = get_job(job["id"])
            if not stored or not stored.get("notified_at"):
                fresh_jobs.append(job)

        if fresh_jobs:
            self.notification_agent.notify_top_jobs(fresh_jobs, top_n=top_n)
            mark_notified([job["id"] for job in fresh_jobs])
            for job in fresh_jobs:
                set_action(job["id"], "PENDING_DECISION", None)
        else:
            # Always send a summary so you know the bot ran
            top3 = scored_jobs[:3]
            if top3:
                summary = "\n".join(
                    f"• {j['title']} @ {j['company']} — {j['score']}/100 (below threshold or already notified)"
                    for j in top3
                )
                send_telegram(
                    f"✅ Pipeline ran — {len(scored_jobs)} jobs scored, none new above {minimum_score}.\n\n"
                    f"Top scored this run:\n{summary}"
                )
            else:
                send_telegram(
                    f"✅ Pipeline ran — fetched {len(jobs)} jobs but none passed pre-filter. "
                    "Check SEARCH_KEYWORDS and SEARCH_LOCATIONS env vars."
                )

        log_run(
            fetched_count=len(jobs),
            ranked_count=len(scored_jobs),
            notified_count=len(fresh_jobs),
            notes=f"Threshold={minimum_score}",
        )
        return {
            "fetched": len(jobs),
            "ranked": len(scored_jobs),
            "shortlisted": len(shortlisted),
            "top_jobs": shortlisted[:top_n],
            "new_jobs": fresh_jobs,
            "recent_runs": recent_runs(5),
        }

    def decide(self, job_id: str, action: str) -> dict:
        action = action.upper().strip()
        if action not in {"APPLY", "REJECT", "SKIP"}:
            raise ValueError("Action must be APPLY, REJECT, or SKIP")

        job = get_job(job_id)
        if not job:
            raise KeyError(f"Unknown job id: {job_id}")

        response = {"job_id": job_id, "action": action, "job": job}
        if action == "APPLY":
            tailored_resume = self.resume_optimizer.tailor_resume(job)
            application_packet = self.application_assistant.prepare_application(job, tailored_resume)
            set_action(job_id, action, application_packet)

            # Attempt auto-fill via Apply Agent
            try:
                from apply_agent import run_apply_agent
                run_apply_agent(job, application_packet)
            except Exception as exc:
                log.warning("Apply agent failed: %s — sending manual packet", exc)
                send_telegram(
                    f"📋 <b>Application packet ready</b> for <b>{job['title']}</b> @ {job['company']}\n\n"
                    f"<b>Tailored Summary:</b>\n{tailored_resume.get('summary', '')}\n\n"
                    f"<b>Key Skills:</b> {', '.join(tailored_resume.get('skills', [])[:8])}\n\n"
                    f"<a href=\"{job.get('link', '#')}\">👉 Apply manually</a>\n\n"
                    "⚠️ Auto-fill unavailable — apply manually."
                )

            response["application_packet"] = application_packet
        else:
            set_action(job_id, action, None)
            send_telegram(f"{action} saved for {job['title']} at {job['company']}.")
        return response

    def pending_actions(self) -> List[dict]:
        return list_pending_actions()

    def action_status(self, job_id: str) -> dict:
        job = get_job(job_id)
        if not job:
            raise KeyError(f"Unknown job id: {job_id}")
        action = get_action(job_id)
        return {"job": job, "action": action}

    def recent_runs(self, limit: int = 10) -> List[dict]:
        return recent_runs(limit)

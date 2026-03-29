"""
agent.py — Steps 4 & 5: Deep Groq scoring + Enrich APPLY jobs only.
Uses fast model (8b) for scoring, quality model (70b) for cover letters.
"""

import json
import logging
import re
from datetime import datetime
from llm_client import call_llm, rule_score_job, rule_cover_letter, rule_resume_bullets, rule_answer_question
from resume_profile import RESUME, get_resume_text

log = logging.getLogger("Agent")
EXCLUDE_COMPANIES = ["capgemini"]


class JobApplicationAgent:
    def __init__(self, groq_api_key: str = ""):
        import os
        if groq_api_key:
            os.environ["GROQ_API_KEY"] = groq_api_key
        self.groq_available = bool(groq_api_key or os.getenv("GROQ_API_KEY"))
        log.info(f"Agent — Groq: {'ON' if self.groq_available else 'OFF'}")

    def _is_excluded(self, company: str) -> bool:
        return any(ex in company.lower() for ex in EXCLUDE_COMPANIES)

    # ── STEP 4: Deep score (fast 8b model) ───────────────────────────────
    def deep_score(self, job: dict) -> dict:
        if not self.groq_available:
            return rule_score_job(job)

        days_ago = job.get("days_ago", 30)
        prompt = f"""Analyze job fit. Return ONLY JSON:
{{"score":0,"decision":"APPLY|MAYBE|SKIP","reasoning":"one sentence","company_type":"product|startup|MNC|consultancy|staffing|unknown","must_have_skills":[],"match_skills":[],"missing_skills":[],"red_flags":[]}}

JOB: {job.get('title')} at {job.get('company')} | {job.get('location')} | {days_ago}d ago
DESCRIPTION: {job.get('description', '')[:1500]}

CANDIDATE: {get_resume_text()}
Notice: {RESUME['notice_period']} | CTC: {RESUME['expected_ctc']} | Relocation: Yes

RULES: APPLY>=65, MAYBE 45-64, SKIP<45
+10 if posted <=3 days, +5 if <=7 days
+10 product/startup, +5 MNC, -20 staffing/body-shop
Return ONLY JSON."""

        result = call_llm(prompt, max_tokens=350, json_mode=True, quality=False)
        if result:
            try:
                d = json.loads(result)
                if "score" in d and "decision" in d:
                    return d
            except:
                pass
        return rule_score_job(job)

    # ── STEP 5a: Cover letter (quality 70b model) ─────────────────────────
    def generate_cover_letter(self, job: dict, score_data: dict) -> str:
        if not self.groq_available:
            return rule_cover_letter(job)
        skills = score_data.get("match_skills", ["Java", "Spring Boot", "Microservices"])[:3]
        prompt = f"""Write a tailored cover letter for {RESUME['name']} applying to {job.get('title')} at {job.get('company')}.
Matching skills: {', '.join(skills)}
JD context: {job.get('description', '')[:400]}
Summary: {RESUME['summary']}
Rules: max 200 words, first person, specific opening, mention Disney/Capgemini scale, 2-3 skills, confident close.
Notice: {RESUME['notice_period']} | CTC: {RESUME['expected_ctc']}
Output ONLY the letter body."""
        result = call_llm(prompt, max_tokens=450, quality=True)
        return result if result else rule_cover_letter(job)

    # ── STEP 5b: Resume bullets (fast 8b model) ───────────────────────────
    def tailor_resume_bullets(self, job: dict, score_data: dict) -> list:
        if not self.groq_available:
            return rule_resume_bullets(job)
        highlights = "\n".join(f"- {h}" for h in RESUME["experience"][0]["highlights"])
        prompt = f"""Tailor resume bullets for: {job.get('title')} at {job.get('company')}
Required: {score_data.get('must_have_skills', [])}
JD: {job.get('description', '')[:300]}

Bullets:
{highlights}

Reorder by JD relevance, rephrase with JD keywords.
Return ONLY a JSON array of 6 bullet strings."""
        result = call_llm(prompt, max_tokens=400, quality=False)
        if result:
            try:
                r = result.strip().lstrip("```json").lstrip("```").rstrip("```")
                bullets = json.loads(r)
                if isinstance(bullets, list) and len(bullets) >= 3:
                    return bullets
            except:
                pass
        return rule_resume_bullets(job)

    def answer_form_question(self, question: str, job_context: dict = None) -> str:
        fast = rule_answer_question(question)
        if fast and fast != "Please refer to my resume for details.":
            return fast
        if not self.groq_available:
            return fast or "Please refer to my attached resume."
        ctx = f"Role: {job_context.get('title')} at {job_context.get('company')}" if job_context else ""
        result = call_llm(
            f"You are {RESUME['name']} filling a job form. Answer in first person, max 60 words.\n"
            f"{ctx}\nResume: {get_resume_text()}\nQuestion: {question}\nAnswer:",
            max_tokens=120, quality=False,
        )
        return result if result else fast or "Please refer to my attached resume."

    def process_job(self, job: dict):
        if self._is_excluded(job.get("company", "")):
            return None

        log.info(f"[Step 4] {job.get('title')} @ {job.get('company')} [{job.get('source','')}] ({job.get('days_ago','?')}d ago)")
        result = {
            "job_id": job["id"], "job_title": job.get("title"),
            "company": job.get("company"), "location": job.get("location"),
            "source": job.get("source", ""), "days_ago": job.get("days_ago", 30),
            "decision": "SKIP", "fit_score": 0, "cover_letter": "",
            "resume_bullets": [], "reasoning": "",
            "apply_url": job.get("apply_url", "#"),
            "timestamp": datetime.now().isoformat(),
        }
        try:
            score_data = self.deep_score(job)
            result["fit_score"] = score_data.get("score", 0)
            result["decision"]  = score_data.get("decision", "SKIP")
            result["reasoning"] = score_data.get("reasoning", "")
            log.info(f"  → {result['decision']} | {result['fit_score']}/100 | {result['reasoning']}")

            if result["decision"] == "APPLY":
                log.info("  [Step 5] Enriching...")
                result["cover_letter"]   = self.generate_cover_letter(job, score_data)
                result["resume_bullets"] = self.tailor_resume_bullets(job, score_data)
        except Exception as e:
            log.error(f"Agent error: {e}")
            fb = rule_score_job(job)
            result.update({
                "fit_score": fb["score"], "decision": fb["decision"], "reasoning": fb["reasoning"],
                "cover_letter": rule_cover_letter(job) if fb["decision"] == "APPLY" else "",
                "resume_bullets": rule_resume_bullets(job) if fb["decision"] == "APPLY" else [],
            })
        return result

    def batch_process(self, jobs: list) -> list:
        results = [self.process_job(j) for j in jobs]
        results = [r for r in results if r is not None]
        order = {"APPLY": 0, "MAYBE": 1, "SKIP": 2}
        results.sort(key=lambda r: (order.get(r["decision"], 3), -r.get("fit_score", 0), r.get("days_ago", 30)))
        return results

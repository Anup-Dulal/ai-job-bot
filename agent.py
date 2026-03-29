"""
agent.py — Steps 4 & 5: Deep Groq scoring + Enrich APPLY jobs only.
Groq gets full resume + full JD context for accurate scoring.
Cover letters and resume bullets only generated for APPLY decisions.
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

    # ── STEP 4: Deep score with full context ─────────────────────────────
    def deep_score(self, job: dict) -> dict:
        """Single Groq call: analyze JD + score + classify company in one shot."""
        if not self.groq_available:
            return rule_score_job(job)

        days_ago = job.get("days_ago", 30)
        source   = job.get("source", "")

        prompt = f"""You are an expert job-fit evaluator. Analyze this job against the candidate resume.
Return ONLY valid JSON with this exact structure:
{{
  "score": 0,
  "decision": "APPLY|MAYBE|SKIP",
  "reasoning": "one clear sentence",
  "company_type": "product|startup|MNC|consultancy|staffing|unknown",
  "must_have_skills": [],
  "match_skills": [],
  "missing_skills": [],
  "red_flags": []
}}

JOB DETAILS:
Title: {job.get('title')}
Company: {job.get('company')} (Source: {source})
Location: {job.get('location')}
Posted: {days_ago} days ago
Description:
{job.get('description', '')[:2000]}

CANDIDATE RESUME:
{get_resume_text()}
Notice: {RESUME['notice_period']} | Expected CTC: {RESUME['expected_ctc']} | Open to relocation: Yes

SCORING RULES (apply all):
- Base score: 0-100 based on skill + experience match
- +10 if posted within 3 days (posted {days_ago} days ago)
- +5 if posted within 7 days
- +10 if company_type is product or startup
- +5 if company_type is MNC
- -20 if company_type is staffing or consultancy body-shop
- -15 if role requires skills candidate clearly lacks
- APPLY >= 65, MAYBE 45-64, SKIP < 45

Return ONLY the JSON. No explanation."""

        result = call_llm(prompt, max_tokens=400, json_mode=True)
        if result:
            try:
                d = json.loads(result)
                if "score" in d and "decision" in d:
                    return d
            except:
                pass
        return rule_score_job(job)

    # ── STEP 5a: Generate cover letter (APPLY only) ───────────────────────
    def generate_cover_letter(self, job: dict, score_data: dict) -> str:
        if not self.groq_available:
            return rule_cover_letter(job)
        skills = score_data.get("match_skills", ["Java", "Spring Boot", "Microservices"])[:3]
        prompt = f"""Write a tailored cover letter for {RESUME['name']} applying to {job.get('title')} at {job.get('company')}.

Key matching skills: {', '.join(skills)}
Job description context: {job.get('description', '')[:500]}
Candidate summary: {RESUME['summary']}

Rules:
- Max 200 words
- First person, professional tone
- Open with something specific about the role/company (not 'I am writing to apply')
- Mention Disney/Capgemini enterprise scale experience
- Reference 2-3 specific matching skills
- End with confident call to action
- Notice: {RESUME['notice_period']} | Expected CTC: {RESUME['expected_ctc']}

Output ONLY the letter body, no subject line."""
        result = call_llm(prompt, max_tokens=450)
        return result if result else rule_cover_letter(job)

    # ── STEP 5b: Tailor resume bullets (APPLY only) ───────────────────────
    def tailor_resume_bullets(self, job: dict, score_data: dict) -> list:
        if not self.groq_available:
            return rule_resume_bullets(job)
        highlights = "\n".join(f"- {h}" for h in RESUME["experience"][0]["highlights"])
        must_have  = score_data.get("must_have_skills", [])
        prompt = f"""Tailor these resume bullets for: {job.get('title')} at {job.get('company')}
Required skills from JD: {must_have}
Job description: {job.get('description', '')[:400]}

Original bullets:
{highlights}

Instructions:
- Reorder bullets by relevance to this specific JD
- Rephrase using keywords from the JD where natural
- Keep bullets achievement-focused and specific
- Return ONLY a JSON array of exactly 6 bullet strings"""
        result = call_llm(prompt, max_tokens=500)
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
            max_tokens=120,
        )
        return result if result else fast or "Please refer to my attached resume."

    def process_job(self, job: dict) -> dict | None:
        if self._is_excluded(job.get("company", "")):
            return None

        log.info(f"[Step 4] Scoring: {job.get('title')} @ {job.get('company')} [{job.get('source','')}] ({job.get('days_ago','?')}d ago)")

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
            # Single Groq call for full analysis
            score_data = self.deep_score(job)
            result["fit_score"] = score_data.get("score", 0)
            result["decision"]  = score_data.get("decision", "SKIP")
            result["reasoning"] = score_data.get("reasoning", "")
            log.info(f"  → {result['decision']} | {result['fit_score']}/100 | {result['reasoning']}")

            # Step 5: Enrich APPLY jobs only
            if result["decision"] == "APPLY":
                log.info(f"  [Step 5] Enriching APPLY job...")
                result["cover_letter"]   = self.generate_cover_letter(job, score_data)
                result["resume_bullets"] = self.tailor_resume_bullets(job, score_data)

        except Exception as e:
            log.error(f"Agent error: {e}")
            fb = rule_score_job(job)
            result.update({
                "fit_score": fb["score"], "decision": fb["decision"],
                "reasoning": fb["reasoning"],
                "cover_letter": rule_cover_letter(job) if fb["decision"] == "APPLY" else "",
                "resume_bullets": rule_resume_bullets(job) if fb["decision"] == "APPLY" else [],
            })
        return result

    def batch_process(self, jobs: list) -> list:
        results = [self.process_job(j) for j in jobs]
        results = [r for r in results if r is not None]
        order = {"APPLY": 0, "MAYBE": 1, "SKIP": 2}
        results.sort(key=lambda r: (
            order.get(r["decision"], 3),
            -r.get("fit_score", 0),
            r.get("days_ago", 30)
        ))
        return results

"""
agent.py — Steps 4 & 5: Deep Groq scoring + Enrich APPLY jobs only.
Processes in batches of 5 with 30s pause to respect Groq rate limits.
Uses fast 8b model for scoring, 70b only for cover letters.
"""

import json
import time
import logging
from datetime import datetime
from llm_client import call_llm, rule_score_job, rule_cover_letter, rule_resume_bullets, rule_answer_question
from resume_profile import RESUME, get_resume_text

log = logging.getLogger("Agent")
EXCLUDE_COMPANIES = ["capgemini"]
BATCH_SIZE  = 5   # jobs per batch
BATCH_PAUSE = 30  # seconds between batches


class JobApplicationAgent:
    def __init__(self, groq_api_key: str = ""):
        import os
        if groq_api_key:
            os.environ["GROQ_API_KEY"] = groq_api_key
        self.groq_available = bool(groq_api_key or os.getenv("GROQ_API_KEY"))
        log.info(f"Agent — Groq: {'ON' if self.groq_available else 'OFF'}")

    def _is_excluded(self, company: str) -> bool:
        return any(ex in company.lower() for ex in EXCLUDE_COMPANIES)

    def deep_score(self, job: dict) -> dict:
        if not self.groq_available:
            return rule_score_job(job)
        days_ago = job.get("days_ago", 30)
        prompt = f"""Analyze job fit. Return ONLY JSON:
{{"score":0,"decision":"APPLY|MAYBE|SKIP","reasoning":"one sentence","company_type":"product|startup|MNC|consultancy|staffing|unknown","must_have_skills":[],"match_skills":[],"missing_skills":[],"red_flags":[]}}

JOB: {job.get('title')} at {job.get('company')} | {job.get('location')} | {days_ago}d ago
DESCRIPTION: {job.get('description', '')[:1200]}

CANDIDATE: {get_resume_text()}
Notice: {RESUME['notice_period']} | CTC: {RESUME['expected_ctc']} | Relocation: Yes

RULES: APPLY>=65, MAYBE 45-64, SKIP<45
+10 posted<=3d, +5 posted<=7d, +10 product/startup, +5 MNC, -20 staffing/body-shop
Return ONLY JSON."""
        result = call_llm(prompt, max_tokens=300, json_mode=True, quality=False)
        if result:
            try:
                d = json.loads(result)
                if "score" in d and "decision" in d:
                    return d
            except:
                pass
        return rule_score_job(job)

    def generate_cover_letter(self, job: dict, score_data: dict) -> str:
        if not self.groq_available:
            return rule_cover_letter(job)
        skills = score_data.get("match_skills", ["Java", "Spring Boot", "Microservices"])[:3]
        prompt = f"""Cover letter for {RESUME['name']} → {job.get('title')} at {job.get('company')}.
Skills: {', '.join(skills)} | JD: {job.get('description', '')[:300]}
Summary: {RESUME['summary']}
Max 180 words. First person. Specific opening. Mention Disney/Capgemini scale. Confident close.
Notice: {RESUME['notice_period']} | CTC: {RESUME['expected_ctc']}
Output ONLY letter body."""
        result = call_llm(prompt, max_tokens=400, quality=True)
        return result if result else rule_cover_letter(job)

    def tailor_resume_bullets(self, job: dict, score_data: dict) -> list:
        if not self.groq_available:
            return rule_resume_bullets(job)
        highlights = "\n".join(f"- {h}" for h in RESUME["experience"][0]["highlights"])
        prompt = f"""Tailor bullets for: {job.get('title')} at {job.get('company')}
Required: {score_data.get('must_have_skills', [])}
{highlights}
Return ONLY JSON array of 6 bullet strings."""
        result = call_llm(prompt, max_tokens=350, quality=False)
        if result:
            try:
                r = result.strip().lstrip("```json").lstrip("```").rstrip("```")
                bullets = json.loads(r)
                if isinstance(bullets, list) and len(bullets) >= 3:
                    return bullets
            except:
                pass
        return rule_resume_bullets(job)

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
        all_results = []
        batches = [jobs[i:i+BATCH_SIZE] for i in range(0, len(jobs), BATCH_SIZE)]
        log.info(f"Processing {len(jobs)} jobs in {len(batches)} batches of {BATCH_SIZE}")

        for i, batch in enumerate(batches):
            log.info(f"--- Batch {i+1}/{len(batches)} ---")
            for job in batch:
                r = self.process_job(job)
                if r:
                    all_results.append(r)
            if i < len(batches) - 1:
                log.info(f"Batch done. Pausing {BATCH_PAUSE}s to respect rate limits...")
                time.sleep(BATCH_PAUSE)

        all_results = [r for r in all_results if r is not None]
        order = {"APPLY": 0, "MAYBE": 1, "SKIP": 2}
        all_results.sort(key=lambda r: (order.get(r["decision"], 3), -r.get("fit_score", 0), r.get("days_ago", 30)))
        return all_results

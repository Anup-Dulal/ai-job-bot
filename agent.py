"""
agent.py — Score jobs with Groq, send results to Telegram.
Cover letter generation removed for now (saves Groq quota).
Processes in batches of 5 with 20s pause between batches.
"""

import json
import time
import logging
from datetime import datetime
from llm_client import call_llm, rule_score_job, rule_answer_question
from resume_profile import RESUME, get_resume_text

log = logging.getLogger("Agent")
EXCLUDE_COMPANIES = ["capgemini"]
BATCH_SIZE  = 5
BATCH_PAUSE = 20


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
{{"score":0,"decision":"APPLY|MAYBE|SKIP","reasoning":"one sentence","company_type":"product|startup|MNC|consultancy|staffing|unknown","match_skills":[],"missing_skills":[]}}

JOB: {job.get('title')} at {job.get('company')} | {job.get('location')} | {days_ago}d ago
DESCRIPTION: {job.get('description', '')[:1000]}

CANDIDATE: {get_resume_text()}
Notice: {RESUME['notice_period']} | CTC: {RESUME['expected_ctc']} | Relocation: Yes

RULES: APPLY>=65, MAYBE 45-64, SKIP<45
+10 posted<=3d, +5 posted<=7d, +10 product/startup, +5 MNC, -20 staffing/body-shop
Return ONLY JSON."""
        result = call_llm(prompt, max_tokens=250, json_mode=True, quality=False)
        if result:
            try:
                d = json.loads(result)
                if "score" in d and "decision" in d:
                    return d
            except:
                pass
        return rule_score_job(job)

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
            max_tokens=100, quality=False,
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
            "decision": "SKIP", "fit_score": 0, "reasoning": "",
            "apply_url": job.get("apply_url", "#"),
            "timestamp": datetime.now().isoformat(),
        }
        try:
            score_data = self.deep_score(job)
            result["fit_score"] = score_data.get("score", 0)
            result["decision"]  = score_data.get("decision", "SKIP")
            result["reasoning"] = score_data.get("reasoning", "")
            log.info(f"  → {result['decision']} | {result['fit_score']}/100 | {result['reasoning']}")
        except Exception as e:
            log.error(f"Agent error: {e}")
            fb = rule_score_job(job)
            result.update({"fit_score": fb["score"], "decision": fb["decision"], "reasoning": fb["reasoning"]})
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
                log.info(f"Pausing {BATCH_PAUSE}s...")
                time.sleep(BATCH_PAUSE)
        order = {"APPLY": 0, "MAYBE": 1, "SKIP": 2}
        all_results.sort(key=lambda r: (order.get(r["decision"], 3), -r.get("fit_score", 0), r.get("days_ago", 30)))
        return all_results

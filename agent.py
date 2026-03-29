"""
agent.py — ReAct Agentic Brain
Primary LLM: Groq API (free tier — Llama 3.3 70B)
Fallback:    Rule-based logic
Now fully resume-driven via resume_profile.py
"""

import json
import logging
import re
from datetime import datetime
from llm_client import call_llm, rule_score_job, rule_cover_letter, rule_resume_bullets, rule_answer_question
from resume_profile import RESUME, get_resume_text

log = logging.getLogger("Agent")


class JobApplicationAgent:
    def __init__(self, groq_api_key: str = ""):
        import os
        if groq_api_key:
            os.environ["GROQ_API_KEY"] = groq_api_key
        self.groq_available = bool(groq_api_key or os.getenv("GROQ_API_KEY"))
        log.info(f"Agent — Groq: {'ON' if self.groq_available else 'OFF (rule-based fallback)'}")

    def analyze_jd(self, job):
        desc = job.get("description", "").lower()
        if not desc or not self.groq_available:
            return self._rule_analyze_jd(job)
        prompt = f"""Analyze this job description against the candidate resume. Return ONLY JSON:
{{"must_have_skills":[],"nice_to_have_skills":[],"experience_required":"","key_responsibilities":[],"red_flags":[],"match_skills":[],"missing_skills":[]}}

Job: {job.get('title')} at {job.get('company')}
Description: {desc[:1500]}

Candidate Resume:
{get_resume_text()}

Return ONLY the JSON."""
        result = call_llm(prompt, max_tokens=400, json_mode=True)
        if result:
            try:
                return json.loads(result)
            except:
                pass
        return self._rule_analyze_jd(job)

    def _rule_analyze_jd(self, job):
        desc = job.get("description", "").lower()
        all_skills = (
            RESUME["skills"]["languages"] +
            RESUME["skills"]["frameworks"] +
            RESUME["skills"]["cloud"] +
            RESUME["skills"]["methodologies"]
        )
        found = [s for s in all_skills if s.lower() in desc]
        m = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*years?", desc)
        return {
            "must_have_skills": found[:5],
            "nice_to_have_skills": found[5:8],
            "experience_required": f"{m.group(1)}-{m.group(2)} years" if m else "Not specified",
            "key_responsibilities": ["Backend development", "API development"],
            "red_flags": [],
            "match_skills": found,
            "missing_skills": [],
        }

    def score_job(self, job, jd_analysis):
        if not self.groq_available:
            return rule_score_job(job)
        prompt = f"""Score this job fit for the candidate (0-100). Return ONLY JSON:
{{"score":0,"decision":"APPLY|MAYBE|SKIP","reasoning":"one sentence","pros":[],"cons":[],"red_flags":[]}}

Job: {job.get('title')} at {job.get('company')} | Location: {job.get('location')}
JD Analysis: {json.dumps(jd_analysis)[:600]}

Candidate:
{get_resume_text()}
Notice: {RESUME['notice_period']} | Expected: {RESUME['expected_ctc']} | Open to relocation: Yes

Rules: APPLY>=65, MAYBE 45-64, SKIP<45. Penalize staffing/body-shop companies.
Return ONLY JSON."""
        result = call_llm(prompt, max_tokens=300, json_mode=True)
        if result:
            try:
                d = json.loads(result)
                if "score" in d and "decision" in d:
                    return d
            except:
                pass
        return rule_score_job(job)

    def generate_cover_letter(self, job, jd_analysis):
        if not self.groq_available:
            return rule_cover_letter(job)
        skills = jd_analysis.get("match_skills", ["Java", "Spring Boot", "Microservices"])[:3]
        prompt = f"""Write a cover letter for {RESUME['name']} applying to {job.get('title')} at {job.get('company')}.
Highlight: {', '.join(skills)}
Resume summary: {RESUME['summary']}
Rules: max 200 words, first person, specific opening (not 'I am writing to apply'),
mention Disney/Capgemini enterprise scale, 2-3 specific tech skills, confident closing.
Notice: {RESUME['notice_period']} | Expected CTC: {RESUME['expected_ctc']}
Output ONLY the letter body."""
        result = call_llm(prompt, max_tokens=450)
        return result if result else rule_cover_letter(job)

    def rewrite_resume_bullets(self, job, jd_analysis):
        if not self.groq_available:
            return rule_resume_bullets(job)
        highlights = "\n".join(f"- {h}" for h in RESUME["experience"][0]["highlights"])
        prompt = f"""Tailor these resume bullets for: {job.get('title')} at {job.get('company')}
Required skills: {jd_analysis.get('must_have_skills', [])}

Original bullets:
{highlights}

Reorder by relevance to JD, rephrase using JD keywords.
Return ONLY a JSON array of 6 bullet strings."""
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

    def answer_form_question(self, question, job_context=None):
        fast = rule_answer_question(question)
        if fast and fast != "Please refer to my resume for details.":
            return fast
        if not self.groq_available:
            return fast or "Please refer to my attached resume."
        ctx = f"Role: {job_context.get('title')} at {job_context.get('company')}" if job_context else ""
        result = call_llm(
            f"You are {RESUME['name']} filling a job application form. Answer in first person, max 60 words.\n"
            f"{ctx}\nResume: {get_resume_text()}\nQuestion: {question}\nAnswer:",
            max_tokens=120,
        )
        return result if result else fast or "Please refer to my attached resume."

    def process_job(self, job):
        log.info(f"\n{'='*50}")
        log.info(f"AGENT: {job.get('title')} @ {job.get('company')}")
        result = {
            "job_id": job["id"],
            "job_title": job.get("title"),
            "company": job.get("company"),
            "decision": "SKIP",
            "fit_score": 0,
            "cover_letter": "",
            "resume_bullets": [],
            "jd_analysis": {},
            "reasoning": "",
            "apply_url": job.get("apply_url", "#"),
            "timestamp": datetime.now().isoformat(),
            "mode": "groq" if self.groq_available else "rules",
        }
        try:
            result["jd_analysis"] = self.analyze_jd(job)
            score_data = self.score_job(job, result["jd_analysis"])
            result["fit_score"] = score_data.get("score", 0)
            result["decision"] = score_data.get("decision", "SKIP")
            result["reasoning"] = score_data.get("reasoning", "")
            log.info(f"  → {result['decision']} | score: {result['fit_score']} | {result['reasoning']}")

            if result["decision"] == "APPLY":
                result["cover_letter"] = self.generate_cover_letter(job, result["jd_analysis"])
                result["resume_bullets"] = self.rewrite_resume_bullets(job, result["jd_analysis"])
        except Exception as e:
            log.error(f"Agent error: {e}")
            fb = rule_score_job(job)
            result.update({
                "fit_score": fb["score"],
                "decision": fb["decision"],
                "reasoning": fb["reasoning"],
                "cover_letter": rule_cover_letter(job) if fb["decision"] == "APPLY" else "",
                "resume_bullets": rule_resume_bullets(job) if fb["decision"] == "APPLY" else [],
            })
        return result

    def batch_process(self, jobs):
        results = [self.process_job(j) for j in jobs]
        order = {"APPLY": 0, "MAYBE": 1, "SKIP": 2}
        results.sort(key=lambda r: (order.get(r["decision"], 3), -r.get("fit_score", 0)))
        return results

"""
agent.py — ReAct Agentic Brain (FREE VERSION)
Primary LLM: Groq API (free tier — 14,400 req/day, Llama 3.3 70B)
Fallback:    Pure rule-based logic (zero cost, works even without internet)

Get free Groq key: https://console.groq.com (no credit card needed)
"""

import json, logging, re
from datetime import datetime
from llm_client import (
    call_llm, rule_score_job, rule_cover_letter,
    rule_resume_bullets, rule_answer_question, ANUP,
)

log = logging.getLogger("Agent")

ANUP_PROFILE = f"""
Name: {ANUP['name']} | Email: {ANUP['email']} | Phone: {ANUP['phone']}
Current: {ANUP['title']} at {ANUP['company']} (client: {ANUP['client']}) — {ANUP['exp_years']}+ years
Skills: Java, Spring Boot, Microservices, REST APIs, AWS, Python, React, JUnit, Mockito, Splunk, Git, Agile
Cert: {ANUP['cert']} | Education: {ANUP['education']}
Notice: {ANUP['notice']} | Expected CTC: {ANUP['ctc_exp']} | Open to relocation: Yes, anywhere in India
"""

class JobApplicationAgent:
    def __init__(self, groq_api_key: str = ""):
        import os
        if groq_api_key:
            os.environ["GROQ_API_KEY"] = groq_api_key
        self.groq_available = bool(groq_api_key or os.getenv("GROQ_API_KEY"))
        log.info(f"Agent — Groq: {'ON' if self.groq_available else 'OFF (rule-based fallback)'}")

    def research_company(self, company, title):
        if not self.groq_available:
            return f"{company} — fallback mode, no research."
        result = call_llm(
            f"In 80 words, describe {company}: what they do, company type (product/service/startup/MNC), "
            f"typical tech stack, culture signals. Role: {title}. If unknown, say so.",
            max_tokens=150
        )
        return result or f"{company} — research unavailable."

    def analyze_jd(self, job):
        desc = job.get("description","").lower()
        if not desc or not self.groq_available:
            return self._rule_analyze_jd(job)
        prompt = f"""Analyze this JD. Return ONLY JSON:
{{"must_have_skills":[],"nice_to_have_skills":[],"experience_required":"","key_responsibilities":[],"red_flags":[],"anup_match_skills":[],"anup_missing_skills":[]}}

Job: {job.get('title')} at {job.get('company')}
Description: {desc[:1000]}
Anup skills: Java,Spring Boot,Microservices,REST APIs,AWS,Python,React,JUnit,Mockito,Splunk,Git,Agile
Return ONLY the JSON."""
        result = call_llm(prompt, max_tokens=350, json_mode=True)
        if result:
            try: return json.loads(result)
            except: pass
        return self._rule_analyze_jd(job)

    def _rule_analyze_jd(self, job):
        desc = job.get("description","").lower()
        skills = ["java","spring boot","spring","microservices","rest api","aws","python",
                  "react","junit","mockito","docker","kubernetes","kafka","sql","git","agile"]
        found = [s for s in skills if s in desc]
        m = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*years?", desc)
        return {
            "must_have_skills": found[:5], "nice_to_have_skills": found[5:8],
            "experience_required": f"{m.group(1)}-{m.group(2)} years" if m else "Not specified",
            "key_responsibilities": ["Backend development","API development","System design"],
            "red_flags": [],
            "anup_match_skills": [s for s in found if s in ANUP["skills"]],
            "anup_missing_skills": [s for s in found if s not in ANUP["skills"]],
        }

    def score_job(self, job, jd_analysis, company_research):
        if not self.groq_available:
            return rule_score_job(job)
        prompt = f"""Score job fit for Anup (0-100). Return ONLY JSON:
{{"score":0,"decision":"APPLY|MAYBE|SKIP","reasoning":"one sentence","pros":[],"cons":[],"red_flags":[]}}

Job: {job.get('title')} at {job.get('company')} | Location: {job.get('location')}
JD: {json.dumps(jd_analysis)[:500]}
Company: {company_research[:200]}
Anup: 4yr Java/Spring Boot/Microservices, AWS Certified, 9-10 LPA, 60-day notice, open relocation
APPLY>=65, MAYBE 45-64, SKIP<45. Return ONLY JSON."""
        result = call_llm(prompt, max_tokens=250, json_mode=True)
        if result:
            try:
                d = json.loads(result)
                if "score" in d and "decision" in d: return d
            except: pass
        return rule_score_job(job)

    def generate_cover_letter(self, job, jd_analysis, company_research):
        if not self.groq_available:
            return rule_cover_letter(job)
        skills = jd_analysis.get("anup_match_skills",["Java","Spring Boot","Microservices"])[:3]
        prompt = f"""Write cover letter for Anup applying to {job.get('title')} at {job.get('company')}.
Company: {company_research[:150]} | Highlight: {', '.join(skills)}
Profile: {ANUP_PROFILE}
Rules: max 200 words, first person, specific opening (not 'I am writing to apply'),
mention Disney/Capgemini scale, 2-3 specific tech skills, confident closing.
Output ONLY the letter body."""
        result = call_llm(prompt, max_tokens=450)
        return result if result else rule_cover_letter(job)

    def rewrite_resume_bullets(self, job, jd_analysis):
        if not self.groq_available:
            return rule_resume_bullets(job)
        prompt = f"""Tailor Anup's resume bullets for: {job.get('title')} at {job.get('company')}
Required: {jd_analysis.get('must_have_skills',[])}
Original:
1. Led end-to-end backend delivery for Disney enterprise platforms (Capgemini)
2. Built scalable microservices with Java/Spring Boot; RESTful APIs
3. Java 8→17 and Spring Boot 1.5→2.7 migration on live systems
4. JUnit + Mockito testing; improved code quality and coverage
5. Production monitoring with Splunk, AppDynamics, Grafana
6. AI-assisted dev with Amazon Q, GitHub Copilot, Kiro
7. Mentored juniors; Agile/Scrum with global onshore teams
Reorder by relevance to JD, rephrase using JD keywords.
Return ONLY a JSON array of 6 bullet strings."""
        result = call_llm(prompt, max_tokens=500)
        if result:
            try:
                r = result.strip().lstrip("```json").lstrip("```").rstrip("```")
                bullets = json.loads(r)
                if isinstance(bullets, list) and len(bullets) >= 3: return bullets
            except: pass
        return rule_resume_bullets(job)

    def answer_form_question(self, question, job_context=None):
        fast = rule_answer_question(question)
        if fast and fast != "Please refer to my resume for details.":
            return fast
        if not self.groq_available:
            return fast or "Please refer to my attached resume."
        ctx = f"Role: {job_context.get('title')} at {job_context.get('company')}" if job_context else ""
        result = call_llm(
            f"You are Anup Dulal filling a job form. Answer in first person, max 60 words.\n{ctx}\n"
            f"Profile: {ANUP_PROFILE}\nQuestion: {question}\nAnswer:",
            max_tokens=120
        )
        return result if result else fast or "Please refer to my attached resume."

    def process_job(self, job):
        log.info(f"\n{'='*50}")
        log.info(f"AGENT [{('groq' if self.groq_available else 'rules')}]: {job.get('title')} @ {job.get('company')}")
        result = {
            "job_id": job["id"], "job_title": job.get("title"), "company": job.get("company"),
            "decision": "SKIP", "fit_score": 0, "cover_letter": "",
            "resume_bullets": [], "company_research": "", "jd_analysis": {},
            "reasoning": "", "timestamp": datetime.now().isoformat(),
            "mode": "groq" if self.groq_available else "rules",
        }
        try:
            log.info("  [1/5] Researching company...")
            result["company_research"] = self.research_company(job.get("company",""), job.get("title",""))

            log.info("  [2/5] Analyzing JD...")
            result["jd_analysis"] = self.analyze_jd(job)

            log.info("  [3/5] Scoring fit...")
            score_data = self.score_job(job, result["jd_analysis"], result["company_research"])
            result["fit_score"] = score_data.get("score", 0)
            result["decision"]  = score_data.get("decision", "SKIP")
            result["reasoning"] = score_data.get("reasoning", "")
            log.info(f"  → {result['decision']} | score: {result['fit_score']} | {result['reasoning']}")

            if result["decision"] == "APPLY":
                log.info("  [4/5] Generating cover letter...")
                result["cover_letter"] = self.generate_cover_letter(job, result["jd_analysis"], result["company_research"])
                log.info("  [5/5] Rewriting resume bullets...")
                result["resume_bullets"] = self.rewrite_resume_bullets(job, result["jd_analysis"])
        except Exception as e:
            log.error(f"  Agent error: {e} — rule fallback")
            fb = rule_score_job(job)
            result.update({"fit_score": fb["score"], "decision": fb["decision"], "reasoning": fb["reasoning"],
                "cover_letter": rule_cover_letter(job) if fb["decision"]=="APPLY" else "",
                "resume_bullets": rule_resume_bullets(job) if fb["decision"]=="APPLY" else []})
        return result

    def batch_process(self, jobs):
        results = [self.process_job(j) for j in jobs]
        order = {"APPLY":0,"MAYBE":1,"SKIP":2}
        results.sort(key=lambda r: (order.get(r["decision"],3), -r.get("fit_score",0)))
        return results

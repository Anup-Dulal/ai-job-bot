"""
llm_client.py — Groq LLM with rate limit handling.
Uses llama-3.1-8b-instant for scoring (faster, higher TPM limit)
Uses llama-3.3-70b-versatile for cover letters only (better quality)
"""

import os
import re
import json
import time
import logging

log = logging.getLogger("LLM")

SCORE_MODEL  = "llama-3.1-8b-instant"       # fast, 20k TPM free
ENRICH_MODEL = "llama-3.3-70b-versatile"    # quality, for cover letters

# Delay between Groq calls to stay under rate limit
CALL_DELAY = 2  # seconds


def _groq_client():
    try:
        from groq import Groq
        key = os.getenv("GROQ_API_KEY", "")
        return Groq(api_key=key) if key else None
    except ImportError:
        return None


def call_llm(prompt: str, system: str = "", max_tokens: int = 600,
             json_mode: bool = False, quality: bool = False) -> str:
    """
    Call Groq. Uses fast model by default, quality model when quality=True.
    """
    client = _groq_client()
    if not client:
        log.warning("Groq not available")
        return ""

    model = ENRICH_MODEL if quality else SCORE_MODEL
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    time.sleep(CALL_DELAY)  # rate limit buffer

    for attempt in range(3):
        try:
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content.strip()
        except Exception as e:
            err = str(e).lower()
            if "rate_limit" in err or "429" in err:
                wait = 15 * (attempt + 1)
                log.warning(f"Groq rate limit — waiting {wait}s (attempt {attempt+1})")
                time.sleep(wait)
            elif "quota" in err or "limit exceeded" in err:
                log.warning("Groq daily quota hit — rule-based fallback")
                return ""
            else:
                log.warning(f"Groq error: {e}")
                return ""
    return ""


# ── Rule-based fallback ───────────────────────────────────────────────────

SKILL_WEIGHTS = {
    "java": 10, "spring boot": 9, "microservices": 8, "spring": 7,
    "rest api": 7, "restful": 7, "aws": 6, "junit": 5, "mockito": 5,
    "git": 4, "agile": 4, "scrum": 4, "python": 4, "sql": 4,
    "docker": 3, "kubernetes": 3, "react": 2, "splunk": 2,
    "appdynamics": 2, "linux": 3, "ci/cd": 3, "jenkins": 2,
    "kafka": 3, "redis": 3, "elasticsearch": 2, "mongodb": 2,
}

GOOD_COMPANY = ["product", "saas", "startup", "unicorn", "mnc", "tech", "software",
                "solutions", "systems", "technologies", "digital", "innovation"]
BAD_COMPANY  = ["consultancy", "staffing", "recruitment", "placement", "manpower", "outsourcing"]
RED_FLAGS    = ["unpaid", "commission only", "no salary", "immediate joiner only"]

EXP_YEARS = 4


def rule_score_job(job: dict) -> dict:
    title    = job.get("title", "").lower()
    company  = job.get("company", "").lower()
    desc     = job.get("description", "").lower()
    location = job.get("location", "").lower()
    combined = f"{title} {desc}"
    score, pros, cons, red_flags = 0, [], [], []

    # Title match
    title_kw = ["java", "backend", "spring", "microservice", "software", "developer", "engineer", "full stack"]
    hits = sum(1 for k in title_kw if k in title)
    score += min(25, hits * 6)
    if hits >= 2: pros.append(f"Title matches Java backend profile ({hits} keywords)")

    # Skill match
    sk_score, matched = 0, []
    for skill, w in SKILL_WEIGHTS.items():
        if skill in combined:
            sk_score += w; matched.append(skill)
    score += min(35, sk_score)
    if matched: pros.append(f"Skills matched: {', '.join(matched[:5])}")

    # Experience
    m = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*years?", combined)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo <= EXP_YEARS <= hi + 1: score += 15; pros.append(f"Exp {lo}-{hi} yrs matches")
        elif EXP_YEARS < lo: score += 5
        else: score += 12
    else:
        score += 10

    # Location
    good_locs = ["noida", "gurgaon", "gurugram", "delhi", "ncr", "bangalore", "bengaluru", "remote", "hybrid"]
    score += 10 if any(l in location for l in good_locs) else 5

    # Company
    if any(s in company for s in BAD_COMPANY): score += 2; cons.append("Staffing/body-shop company")
    elif any(s in company for s in GOOD_COMPANY): score += 10; pros.append("Product/tech company")
    else: score += 6

    # Red flags
    for flag in RED_FLAGS:
        if flag in combined: score -= 10; red_flags.append(flag)

    # Recency bonus
    days = job.get("days_ago", 30)
    if days <= 1: score += 8
    elif days <= 3: score += 5
    elif days <= 7: score += 2

    score = max(0, min(100, score))
    decision = "APPLY" if score >= 65 else "MAYBE" if score >= 45 else "SKIP"
    return {
        "score": score, "decision": decision, "pros": pros, "cons": cons,
        "red_flags": red_flags, "match_skills": matched,
        "reasoning": f"Rule-based score {score}/100. {pros[0] if pros else ''}",
        "company_type": "unknown", "must_have_skills": matched[:3], "missing_skills": [],
    }


def rule_cover_letter(job: dict) -> str:
    title, company = job.get("title", "the role"), job.get("company", "your company")
    desc = job.get("description", "").lower()
    highlights = [s.title() for s in ["spring boot", "microservices", "java", "aws", "rest api"] if s in desc][:3]
    if not highlights: highlights = ["Java", "Spring Boot", "Microservices"]
    return f"""Dear Hiring Manager,

I was excited to come across the {title} position at {company}. With 4+ years of backend development experience at Capgemini — where I led feature delivery for Disney's enterprise platforms — I believe I can bring immediate impact to your team.

My expertise in {', '.join(highlights)} aligns with your requirements. I designed scalable microservices using Spring Boot, executed a Java 8→17 migration on live systems, and hold AWS Cloud Practitioner certification.

I am available with 60 days notice and open to relocation. Expected CTC: 9-10 LPA.

Sincerely,
Anup Dulal | Anupdulal2012@gmail.com | +917455896497"""


def rule_resume_bullets(job: dict) -> list:
    desc = job.get("description", "").lower()
    bullets = [
        "Led end-to-end backend delivery for Disney enterprise platforms (Capgemini), owning design to deployment",
        "Built scalable microservices using Java 17, Spring Boot 2.7, REST APIs on AWS EC2/S3",
        "Executed Java 8→17 and Spring Boot 1.5→2.7 migration on live system with zero downtime",
        "Improved code quality via JUnit and Mockito testing; reduced production bugs systematically",
        "Monitored production with Splunk, AppDynamics, Grafana; provided timely incident resolution",
        "Developed Python automation scripts reducing application load times",
        "Collaborated with global onshore teams using Agile/Scrum; mentored junior developers",
    ]
    priority = [b for b in bullets if any(k in desc for k in ["microservice", "spring", "java", "aws"])]
    rest = [b for b in bullets if b not in priority]
    return (priority + rest)[:6]


def rule_answer_question(question: str) -> str:
    from qa_engine import answer_question
    return answer_question(question)

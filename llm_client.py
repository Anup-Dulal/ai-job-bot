"""
llm_client.py — Free LLM Layer
Primary:  Groq API (free tier, 14,400 req/day, Llama 3.3 70B)
Fallback: Rule-based logic (zero cost, zero API calls)

Get your free Groq key at: https://console.groq.com (no credit card)
"""

import os
import re
import json
import time
import logging

log = logging.getLogger("LLM")

# ── Groq client (lazy import) ─────────────────────────────────────────────
def _groq_client():
    try:
        from groq import Groq
        key = os.getenv("GROQ_API_KEY", "")
        if not key:
            return None
        return Groq(api_key=key)
    except ImportError:
        return None


def call_llm(prompt: str, system: str = "", max_tokens: int = 600, json_mode: bool = False) -> str:
    """
    Call Groq (free). Falls back to rule-based if quota hit or key missing.
    """
    client = _groq_client()
    if not client:
        log.warning("Groq not available — using rule-based fallback")
        return ""

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs = {
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(3):
        try:
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content.strip()
        except Exception as e:
            err = str(e).lower()
            if "rate_limit" in err or "429" in err:
                wait = 10 * (attempt + 1)
                log.warning(f"Groq rate limit — waiting {wait}s")
                time.sleep(wait)
            elif "quota" in err or "limit exceeded" in err:
                log.warning("Groq daily quota hit — switching to rule-based fallback")
                return ""
            else:
                log.warning(f"Groq error: {e}")
                return ""
    return ""


# ── Rule-based fallback engine ────────────────────────────────────────────
# No API calls, no cost, works forever

ANUP = {
    "name":        "Anup Dulal",
    "email":       "Anupdulal2012@gmail.com",
    "phone":       "+917455896497",
    "location":    "Ghaziabad, UP",
    "title":       "Java Backend Developer",
    "company":     "Capgemini Technology Services",
    "client":      "Disney",
    "exp_years":   4,
    "notice":      "60 days",
    "ctc_exp":     "9-10 LPA",
    "ctc_curr":    "As per industry standard",
    "education":   "B.Tech Computer Science, IIMT University Meerut 2021",
    "cert":        "AWS Certified Cloud Practitioner",
    "github":      "https://github.com/Anup-Dulal",
    "skills": {
        "java": 4, "spring boot": 4, "spring": 4, "microservices": 3,
        "rest api": 4, "restful": 4, "aws": 2, "python": 2, "react": 1,
        "junit": 3, "mockito": 3, "git": 4, "agile": 4, "scrum": 4,
        "sql": 3, "splunk": 2, "appdynamics": 2, "grafana": 1,
        "ec2": 2, "s3": 2, "docker": 1, "linux": 2,
    },
    "switch_reason": (
        "I have had a great experience at Capgemini working on enterprise-level projects "
        "for Disney, but I am now looking for an opportunity that offers greater technical "
        "ownership, product-focused environment, and accelerated career growth. I want to "
        "deepen my expertise in distributed systems and cloud-native architecture."
    ),
    "summary": (
        "Results-driven Java Backend Developer with 4+ years at Capgemini (client: Disney), "
        "delivering scalable enterprise applications using Spring Boot, Microservices, and AWS. "
        "AWS Certified Cloud Practitioner. Experienced in AI-assisted development tools."
    ),
}

# Skill match weights — how much each skill matters for Java Backend roles
SKILL_WEIGHTS = {
    "java": 10, "spring boot": 9, "microservices": 8, "spring": 7,
    "rest api": 7, "restful": 7, "aws": 6, "junit": 5, "mockito": 5,
    "git": 4, "agile": 4, "scrum": 4, "python": 4, "sql": 4,
    "docker": 3, "kubernetes": 3, "react": 2, "splunk": 2,
    "appdynamics": 2, "linux": 3, "ci/cd": 3, "jenkins": 2,
    "kafka": 3, "redis": 3, "elasticsearch": 2, "mongodb": 2,
}

# Company quality signals
GOOD_COMPANY_SIGNALS  = ["product", "saas", "startup", "unicorn", "mnc", "tech", "software",
                          "solutions", "systems", "technologies", "digital", "innovation"]
BAD_COMPANY_SIGNALS   = ["consultancy", "staffing", "recruitment", "placement", "manpower",
                          "body shop", "outsourcing"]
RED_FLAG_JD_WORDS     = ["unpaid", "commission only", "no salary", "fake", "urgent requirement",
                          "immediate joiner only", "no experience needed", "work from home scam"]


def rule_score_job(job: dict) -> dict:
    """
    Score a job purely with rules — no API call needed.
    Returns score 0-100, decision, pros, cons, red_flags.
    """
    title       = job.get("title", "").lower()
    company     = job.get("company", "").lower()
    description = job.get("description", "").lower()
    location    = job.get("location", "").lower()
    combined    = f"{title} {description}"

    score = 0
    pros, cons, red_flags = [], [], []

    # ── 1. Title match (0-25 pts) ─────────────────────────────────────────
    title_keywords = ["java", "backend", "spring", "microservice", "software", "developer",
                      "engineer", "associate", "consultant", "full stack", "api"]
    title_hits = sum(1 for k in title_keywords if k in title)
    title_score = min(25, title_hits * 6)
    score += title_score
    if title_hits >= 2:
        pros.append(f"Title matches Java backend profile ({title_hits} keywords)")
    elif title_hits == 0:
        cons.append("Job title doesn't match backend developer profile")

    # ── 2. Skill match in JD (0-35 pts) ──────────────────────────────────
    skill_score = 0
    matched_skills = []
    for skill, weight in SKILL_WEIGHTS.items():
        if skill in combined:
            skill_score += weight
            matched_skills.append(skill)
    skill_score = min(35, skill_score)
    score += skill_score
    if matched_skills:
        pros.append(f"Skills matched: {', '.join(matched_skills[:5])}")
    else:
        cons.append("No recognizable tech skills found in JD")

    # ── 3. Experience level (0-15 pts) ───────────────────────────────────
    exp_patterns = [
        (r"(\d+)\s*[-–]\s*(\d+)\s*years?", "range"),
        (r"(\d+)\+\s*years?", "min"),
        (r"(\d+)\s*years?", "exact"),
    ]
    exp_score = 10  # default neutral
    for pattern, kind in exp_patterns:
        m = re.search(pattern, combined)
        if m:
            if kind == "range":
                lo, hi = int(m.group(1)), int(m.group(2))
                if lo <= ANUP["exp_years"] <= hi + 1:
                    exp_score = 15; pros.append(f"Experience {lo}-{hi} yrs matches Anup's {ANUP['exp_years']} yrs")
                elif ANUP["exp_years"] < lo:
                    exp_score = 5;  cons.append(f"Requires {lo}+ yrs, Anup has {ANUP['exp_years']} yrs")
                else:
                    exp_score = 12
            elif kind == "min":
                req = int(m.group(1))
                exp_score = 15 if ANUP["exp_years"] >= req else max(0, 10 - (req - ANUP["exp_years"]) * 3)
            break
    score += exp_score

    # ── 4. Location fit (0-10 pts) ────────────────────────────────────────
    good_locs = ["noida", "gurgaon", "gurugram", "delhi", "ncr", "bangalore",
                 "bengaluru", "remote", "work from home", "hybrid"]
    if any(loc in location for loc in good_locs):
        score += 10; pros.append(f"Location {location} matches preferences")
    elif location:
        score += 5;  cons.append(f"Location {location} not in preferred list (but open to relocation)")
    else:
        score += 7

    # ── 5. Company quality (0-10 pts) ─────────────────────────────────────
    if any(s in company for s in BAD_COMPANY_SIGNALS):
        score += 2; cons.append(f"'{company}' looks like a staffing/body-shop company")
    elif any(s in company for s in GOOD_COMPANY_SIGNALS):
        score += 10; pros.append(f"'{company}' looks like a product/tech company")
    else:
        score += 6  # neutral

    # ── 6. Red flags (-10 each) ───────────────────────────────────────────
    for flag in RED_FLAG_JD_WORDS:
        if flag in combined:
            score -= 10
            red_flags.append(flag)

    score = max(0, min(100, score))

    # Decision
    if red_flags and len(red_flags) >= 2:
        decision = "SKIP"
    elif score >= 65:
        decision = "APPLY"
    elif score >= 45:
        decision = "MAYBE"
    else:
        decision = "SKIP"

    return {
        "score": score,
        "decision": decision,
        "pros": pros,
        "cons": cons,
        "red_flags": red_flags,
        "reasoning": f"Rule-based score {score}/100. {pros[0] if pros else ''}"
    }


def rule_cover_letter(job: dict) -> str:
    """Generate a good cover letter using templates + Anup's data. No API."""
    title   = job.get("title", "the role")
    company = job.get("company", "your company")
    desc    = job.get("description", "").lower()

    highlights = []
    priority_skills = ["spring boot", "microservices", "java", "aws", "rest api",
                       "python", "react", "junit", "docker", "kafka"]
    for skill in priority_skills:
        if skill in desc and len(highlights) < 3:
            highlights.append(skill.title())
    if not highlights:
        highlights = ["Java", "Spring Boot", "Microservices"]

    skills_str = ", ".join(highlights)

    return f"""Dear Hiring Manager,

I was excited to come across the {title} position at {company}. With 4+ years of backend development experience at Capgemini — where I led feature delivery for Disney's enterprise platforms — I believe I can bring immediate, meaningful impact to your team.

My core expertise in {skills_str} aligns directly with what you are looking for. At Capgemini, I designed and built scalable microservices using Spring Boot, executed a full Java 8→17 and Spring Boot migration on live enterprise systems, and improved code reliability through JUnit and Mockito testing. I am also an AWS Certified Cloud Practitioner and actively use AI-assisted development tools like GitHub Copilot and Amazon Q to improve delivery speed.

I am currently serving a 60-day notice period and am open to relocating anywhere in India. My expected CTC is 9–10 LPA.

I would welcome the opportunity to discuss how my background can contribute to {company}'s goals.

Sincerely,
Anup Dulal
Anupdulal2012@gmail.com | +917455896497
https://github.com/Anup-Dulal"""


def rule_resume_bullets(job: dict) -> list:
    """Return resume bullets reordered/rephrased for the job. No API."""
    desc = job.get("description", "").lower()

    all_bullets = [
        "Led end-to-end backend feature delivery from offshore team for Disney (via Capgemini), owning design to deployment",
        "Built and maintained scalable microservices using Java 17, Spring Boot 2.7, and REST APIs on AWS EC2/S3",
        "Executed full Java 8→17 and Spring Boot 1.5→2.7 migration on live enterprise system with zero production downtime",
        "Improved code quality and test coverage using JUnit and Mockito; reduced production bugs by systematic unit testing",
        "Monitored and debugged production incidents using Splunk, AppDynamics, and Grafana; provided timely resolution",
        "Developed Python automation scripts to optimize cache-clearing, reducing application load times",
        "Collaborated with global onshore teams (US timezone) using Agile/Scrum methodology for cross-timezone delivery",
        "Used AI-assisted tools (Amazon Q, GitHub Copilot, Kiro) to accelerate development and improve code quality",
        "Mentored junior developers, conducted code reviews, and resolved technical blockers across the team",
    ]

    priority = []
    secondary = []
    for bullet in all_bullets:
        b_lower = bullet.lower()
        if any(kw in desc for kw in ["microservice", "spring", "java", "aws", "api"]) and \
           any(kw in b_lower for kw in ["microservice", "spring", "java", "aws", "api"]):
            priority.append(bullet)
        else:
            secondary.append(bullet)

    return (priority + secondary)[:7]


def rule_answer_question(question: str) -> str:
    """Answer any form question using rules. No API."""
    from qa_engine import answer_question
    return answer_question(question)

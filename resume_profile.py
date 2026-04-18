"""
resume_profile.py — Candidate profile loaded from env with safe defaults.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict


DEFAULT_RESUME: Dict[str, Any] = {
    "name": "Candidate Name",
    "email": "candidate@example.com",
    "phone": "+910000000000",
    "location": "India",
    "title": "Java Backend Developer",
    "experience_years": 4,
    "current_company": "Current Employer",
    "current_client": "Confidential Client",
    "notice_period": "60 days",
    "expected_ctc": "Flexible",
    "education": "B.Tech Computer Science",
    "certifications": ["AWS Certified Cloud Practitioner"],
    "awards": [],
    "skills": {
        "languages": ["Java", "Python", "C++"],
        "frameworks": ["Spring", "Spring Boot", "JUnit", "Mockito", "REST APIs", "React"],
        "cloud": ["AWS EC2", "AWS S3"],
        "observability": ["AppDynamics", "Splunk", "Grafana"],
        "ai_tools": ["Amazon Q", "GitHub Copilot", "Kiro"],
        "methodologies": ["Agile", "Scrum", "OOP", "Microservices Architecture"],
        "databases": ["SQL"],
        "tools": ["Git", "Eclipse", "VS Code", "Spring Tool Suite"],
    },
    "experience": [
        {
            "company": "Current Employer",
            "client": "Confidential Client",
            "role": "Java Backend Developer",
            "duration": "2022 - Present",
            "highlights": [
                "Built scalable microservices using Java and Spring Boot",
                "Developed RESTful APIs for enterprise systems",
                "Improved backend quality using JUnit and Mockito",
            ],
        }
    ],
    "projects": [
        "Online Crop Deal System — Spring Boot, React, Microservices",
        "Mask Detection System — Python, ML, OpenCV, YOLO",
    ],
    "summary": (
        "Results-driven Java Backend Developer with strong Spring Boot, REST API, and "
        "microservices experience. Comfortable with AWS, testing, production support, and "
        "collaborating in Agile teams."
    ),
    "ideal_job": {
        "roles": [
            "Java Backend Developer",
            "Java Developer",
            "Spring Boot Developer",
            "Backend Engineer",
            "Software Engineer - Java",
            "Microservices Developer",
        ],
        "locations": ["Noida", "Gurgaon", "Delhi NCR", "Bangalore", "Hyderabad", "Remote"],
        "exp_range": "3-6 years",
        "company_type": "product company or good MNC",
        "avoid": ["staffing", "recruitment", "placement", "body shop"],
    },
}


def _split_env_list(name: str, fallback: list[str]) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return fallback
    # Support both comma and pipe as separators (Render env vars may use either)
    separator = "|" if "|" in raw and "," not in raw else ","
    return [item.strip() for item in raw.split(separator) if item.strip()]


def _load_profile_file() -> Dict[str, Any]:
    path = os.getenv("PROFILE_JSON_PATH", "").strip()
    if not path:
        return {}
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        return json.loads(file_path.read_text())
    except Exception:
        return {}


def _merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_resume() -> Dict[str, Any]:
    resume = deepcopy(DEFAULT_RESUME)
    resume = _merge(resume, _load_profile_file())

    simple_overrides = {
        "name": os.getenv("PROFILE_NAME"),
        "email": os.getenv("PROFILE_EMAIL"),
        "phone": os.getenv("PROFILE_PHONE"),
        "location": os.getenv("PROFILE_LOCATION"),
        "title": os.getenv("PROFILE_TITLE"),
        "current_company": os.getenv("PROFILE_CURRENT_COMPANY"),
        "current_client": os.getenv("PROFILE_CURRENT_CLIENT"),
        "notice_period": os.getenv("PROFILE_NOTICE"),
        "expected_ctc": os.getenv("PROFILE_CTC_EXP"),
        "education": os.getenv("PROFILE_EDUCATION"),
        "summary": os.getenv("PROFILE_SUMMARY"),
    }
    for key, value in simple_overrides.items():
        if value:
            resume[key] = value

    exp_years = os.getenv("PROFILE_EXP_YEARS")
    if exp_years and exp_years.isdigit():
        resume["experience_years"] = int(exp_years)

    resume["certifications"] = _split_env_list("PROFILE_CERTIFICATIONS", resume["certifications"])
    resume["awards"] = _split_env_list("PROFILE_AWARDS", resume["awards"])
    resume["projects"] = _split_env_list("PROFILE_PROJECTS", resume["projects"])
    resume["ideal_job"]["roles"] = _split_env_list("SEARCH_KEYWORDS", resume["ideal_job"]["roles"])
    resume["ideal_job"]["locations"] = _split_env_list("SEARCH_LOCATIONS", resume["ideal_job"]["locations"])

    for section, env_name in {
        "languages": "PROFILE_SKILLS_LANGUAGES",
        "frameworks": "PROFILE_SKILLS_FRAMEWORKS",
        "cloud": "PROFILE_SKILLS_CLOUD",
        "observability": "PROFILE_SKILLS_OBSERVABILITY",
        "ai_tools": "PROFILE_SKILLS_AI_TOOLS",
        "methodologies": "PROFILE_SKILLS_METHODOLOGIES",
        "databases": "PROFILE_SKILLS_DATABASES",
        "tools": "PROFILE_SKILLS_TOOLS",
    }.items():
        resume["skills"][section] = _split_env_list(env_name, resume["skills"].get(section, []))

    return resume


RESUME = load_resume()


def get_resume_text() -> str:
    """Return resume as plain text for prompts and generated artifacts."""
    skills_flat = []
    for values in RESUME["skills"].values():
        skills_flat.extend(values)

    experience_lines = []
    for item in RESUME.get("experience", []):
        experience_lines.append(
            f"{item.get('role', '')} at {item.get('company', '')} ({item.get('duration', '')})"
        )
        for highlight in item.get("highlights", []):
            experience_lines.append(f"- {highlight}")

    return (
        f"Name: {RESUME['name']}\n"
        f"Title: {RESUME['title']}\n"
        f"Experience: {RESUME['experience_years']}+ years\n"
        f"Location: {RESUME['location']}\n"
        f"Current: {RESUME['current_company']} (client: {RESUME['current_client']})\n"
        f"Skills: {', '.join(skills_flat)}\n"
        f"Certifications: {', '.join(RESUME['certifications'])}\n"
        f"Education: {RESUME['education']}\n"
        f"Notice: {RESUME['notice_period']} | Expected CTC: {RESUME['expected_ctc']}\n"
        f"Summary: {RESUME['summary']}\n"
        f"Projects: {', '.join(RESUME.get('projects', []))}\n"
        f"Experience Details:\n" + "\n".join(experience_lines)
    )

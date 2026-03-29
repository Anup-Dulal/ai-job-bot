"""
qa_engine.py — Rule-based Q&A for job application form questions.
No API calls, zero cost.
"""

import os
import re

# Pull profile from env vars (with sensible fallbacks)
_NAME     = os.getenv("PROFILE_NAME", "Anup Dulal")
_EMAIL    = os.getenv("PROFILE_EMAIL", "")
_PHONE    = os.getenv("PROFILE_PHONE", "")
_LOCATION = os.getenv("PROFILE_LOCATION", "Ghaziabad, UP")
_EXP      = os.getenv("PROFILE_EXP_YEARS", "4")
_TITLE    = os.getenv("PROFILE_TITLE", "Java Backend Developer")
_NOTICE   = os.getenv("PROFILE_NOTICE", "60 days")
_CTC_EXP  = os.getenv("PROFILE_CTC_EXP", "9-10 LPA")
_GITHUB   = os.getenv("PROFILE_GITHUB", "")

QA_MAP = [
    # Experience
    (r"how many years", f"I have {_EXP}+ years of professional experience in Java backend development."),
    (r"years of experience", f"{_EXP}+ years in Java, Spring Boot, and Microservices."),
    (r"total experience", f"{_EXP}+ years."),

    # Notice period
    (r"notice period", f"My current notice period is {_NOTICE}."),
    (r"when can you join", f"I can join within {_NOTICE} from the date of offer."),
    (r"earliest.*join|join.*earliest", f"I can join within {_NOTICE}."),

    # Salary / CTC
    (r"expected.*ctc|expected.*salary|salary.*expectation", f"My expected CTC is {_CTC_EXP}."),
    (r"current.*ctc|current.*salary", "As per industry standard."),

    # Location
    (r"willing to relocate|open to relocation", "Yes, I am open to relocating anywhere in India."),
    (r"current.*location|where are you based", f"I am currently based in {_LOCATION}."),

    # Why leaving
    (r"why.*leaving|reason.*change|why.*switch",
     "I am looking for greater technical ownership, a product-focused environment, "
     "and accelerated career growth in distributed systems and cloud-native architecture."),

    # Skills
    (r"primary.*skill|key.*skill|core.*skill",
     "Java 17, Spring Boot, Microservices, REST APIs, AWS, JUnit, Mockito, Git, Agile."),
    (r"aws|cloud", "I am an AWS Certified Cloud Practitioner with hands-on EC2 and S3 experience."),

    # Education
    (r"education|degree|qualification",
     "B.Tech in Computer Science from IIMT University Meerut, 2021."),

    # Contact
    (r"github|portfolio", _GITHUB or "Please refer to my resume."),
    (r"email", _EMAIL or "Please refer to my resume."),
    (r"phone|contact number", _PHONE or "Please refer to my resume."),

    # Generic
    (r"tell me about yourself|introduce yourself",
     f"I am a {_TITLE} with {_EXP}+ years of experience at Capgemini, "
     "delivering enterprise-scale backend systems for Disney using Java, Spring Boot, "
     "and Microservices. I am AWS Certified and passionate about clean, scalable architecture."),
]


def answer_question(question: str) -> str:
    q = question.lower().strip()
    for pattern, answer in QA_MAP:
        if re.search(pattern, q):
            return answer
    return "Please refer to my resume for details."

"""
qa_engine.py — Rule-based answers for common application questions.
"""

from __future__ import annotations

import re

from resume_profile import RESUME

QA_MAP = [
    (r"how many years|years of experience|total experience",
     f"{RESUME['experience_years']}+ years in Java, Spring Boot, and backend development."),
    (r"notice period|when can you join|earliest.*join|join.*earliest",
     f"My current notice period is {RESUME['notice_period']}."),
    (r"expected.*ctc|expected.*salary|salary.*expectation",
     f"My expected CTC is {RESUME['expected_ctc']}."),
    (r"current.*location|where are you based",
     f"I am currently based in {RESUME['location']}."),
    (r"willing to relocate|open to relocation",
     "Yes, I am open to relocating for the right opportunity."),
    (r"why.*leaving|reason.*change|why.*switch",
     "I am looking for greater backend ownership, product impact, and continued growth in distributed systems."),
    (r"primary.*skill|key.*skill|core.*skill",
     "Java, Spring Boot, Microservices, REST APIs, AWS, JUnit, Mockito, SQL, and Git."),
    (r"aws|cloud",
     "I have hands-on AWS experience and I am comfortable working with cloud-based backend systems."),
    (r"education|degree|qualification",
     RESUME["education"]),
    (r"github|portfolio", "Please refer to my resume or profile links provided with the application."),
    (r"email", RESUME["email"]),
    (r"phone|contact number", RESUME["phone"]),
    (
        r"tell me about yourself|introduce yourself",
        f"I am a {RESUME['title']} with {RESUME['experience_years']}+ years of experience building "
        "Java backend systems using Spring Boot, REST APIs, and microservices."
    ),
]


def answer_question(question: str) -> str:
    text = question.lower().strip()
    for pattern, answer in QA_MAP:
        if re.search(pattern, text):
            return answer
    return "Please refer to my resume for details."

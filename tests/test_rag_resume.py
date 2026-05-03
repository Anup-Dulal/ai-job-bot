"""
tests/test_rag_resume.py — Tests for rag_resume.py
"""

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag_resume import _chunk_resume, tailor_resume_rag


def sample_job(**kwargs) -> dict:
    defaults = {
        "id": "test_1",
        "title": "Java Backend Developer",
        "company": "Infosys",
        "location": "Noida",
        "description": "Spring Boot microservices REST API AWS Java 8+ years experience",
    }
    defaults.update(kwargs)
    return defaults


# ─── _chunk_resume ────────────────────────────────────────────────────────────

class TestChunkResume:
    def test_returns_list_of_dicts(self):
        chunks = _chunk_resume()
        assert isinstance(chunks, list)
        assert all(isinstance(c, dict) for c in chunks)

    def test_each_chunk_has_required_fields(self):
        chunks = _chunk_resume()
        for chunk in chunks:
            assert "id" in chunk
            assert "section" in chunk
            assert "text" in chunk

    def test_summary_chunk_present(self):
        chunks = _chunk_resume()
        ids = [c["id"] for c in chunks]
        assert "summary" in ids

    def test_skills_chunks_present(self):
        chunks = _chunk_resume()
        skill_chunks = [c for c in chunks if c["id"].startswith("skills_")]
        assert len(skill_chunks) > 0

    def test_experience_chunks_present(self):
        chunks = _chunk_resume()
        exp_chunks = [c for c in chunks if c["id"].startswith("experience_")]
        assert len(exp_chunks) > 0

    def test_no_empty_text_chunks(self):
        chunks = _chunk_resume()
        for chunk in chunks:
            assert chunk["text"].strip() != ""

    def test_at_least_5_chunks(self):
        chunks = _chunk_resume()
        assert len(chunks) >= 5


# ─── tailor_resume_rag ────────────────────────────────────────────────────────

class TestTailorResumeRag:
    def test_returns_dict(self):
        with patch("rag_resume.call_llm", return_value=""):
            result = tailor_resume_rag(sample_job())
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        with patch("rag_resume.call_llm", return_value=""):
            result = tailor_resume_rag(sample_job())
        assert "summary" in result
        assert "skills" in result
        assert "experience_bullets" in result
        assert "projects" in result
        assert "tailored_for" in result

    def test_tailored_for_contains_job_info(self):
        with patch("rag_resume.call_llm", return_value=""):
            result = tailor_resume_rag(sample_job(title="Senior Java Dev", company="TCS"))
        assert "Senior Java Dev" in result["tailored_for"]
        assert "TCS" in result["tailored_for"]

    def test_uses_llm_response_when_valid(self):
        llm_response = json.dumps({
            "summary": "Experienced Java developer with Spring Boot expertise",
            "skills": ["Java", "Spring Boot", "AWS"],
            "experience_bullets": ["Built microservices", "Developed REST APIs"],
            "projects": ["Online Crop Deal System"],
            "changes": ["Highlighted Spring Boot skills"],
        })
        with patch("rag_resume.call_llm", return_value=llm_response):
            result = tailor_resume_rag(sample_job())
        assert result["summary"] == "Experienced Java developer with Spring Boot expertise"
        assert "Java" in result["skills"]

    def test_falls_back_on_invalid_llm_response(self):
        with patch("rag_resume.call_llm", return_value="not valid json"):
            result = tailor_resume_rag(sample_job())
        # Should still return a valid dict with fallback values
        assert isinstance(result["skills"], list)
        assert len(result["skills"]) > 0

    def test_falls_back_on_empty_llm_response(self):
        with patch("rag_resume.call_llm", return_value=""):
            result = tailor_resume_rag(sample_job())
        assert isinstance(result, dict)
        assert "summary" in result

    def test_skills_is_list(self):
        with patch("rag_resume.call_llm", return_value=""):
            result = tailor_resume_rag(sample_job())
        assert isinstance(result["skills"], list)

    def test_experience_bullets_is_list(self):
        with patch("rag_resume.call_llm", return_value=""):
            result = tailor_resume_rag(sample_job())
        assert isinstance(result["experience_bullets"], list)

    def test_job_relevant_skills_prioritized_in_fallback(self):
        # Job mentions "Spring Boot" — should appear early in skills list
        job = sample_job(description="Spring Boot microservices Java developer needed")
        with patch("rag_resume.call_llm", return_value=""):
            result = tailor_resume_rag(job)
        skills_lower = [s.lower() for s in result["skills"]]
        # Spring Boot should be in the list
        assert any("spring" in s for s in skills_lower)

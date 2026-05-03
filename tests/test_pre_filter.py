"""
tests/test_pre_filter.py — Tests for pre_filter.py
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pre_filter import pre_filter, _exp_match


def make_job(**kwargs) -> dict:
    defaults = {
        "id": "test_1",
        "title": "Java Backend Developer",
        "company": "Infosys",
        "location": "Noida",
        "description": "Spring Boot microservices REST API",
        "source": "Naukri",
    }
    defaults.update(kwargs)
    return defaults


# ─── _exp_match ───────────────────────────────────────────────────────────────

class TestExpMatch:
    def test_matching_range_passes(self):
        assert _exp_match("3-5 years experience") is True

    def test_too_junior_fails(self):
        assert _exp_match("0-1 year experience") is False

    def test_too_senior_fails(self):
        assert _exp_match("10-15 years experience") is False

    def test_plus_notation_passes(self):
        assert _exp_match("3+ years") is True

    def test_plus_notation_too_senior_fails(self):
        assert _exp_match("10+ years") is False

    def test_no_experience_mentioned_passes(self):
        assert _exp_match("Java Spring Boot developer") is True

    def test_boundary_2_years_passes(self):
        assert _exp_match("2-4 years") is True

    def test_boundary_8_years_passes(self):
        assert _exp_match("6-8 years") is True


# ─── pre_filter ───────────────────────────────────────────────────────────────

class TestPreFilter:
    def test_relevant_java_job_kept(self):
        jobs = [make_job(title="Java Backend Developer")]
        result = pre_filter(jobs)
        assert len(result) == 1

    def test_spring_boot_job_kept(self):
        jobs = [make_job(title="Spring Boot Developer")]
        result = pre_filter(jobs)
        assert len(result) == 1

    def test_frontend_job_dropped(self):
        jobs = [make_job(title="React Frontend Developer")]
        result = pre_filter(jobs)
        assert len(result) == 0

    def test_javascript_job_dropped(self):
        jobs = [make_job(title="JavaScript Developer")]
        result = pre_filter(jobs)
        assert len(result) == 0

    def test_qa_job_dropped(self):
        jobs = [make_job(title="QA Tester")]
        result = pre_filter(jobs)
        assert len(result) == 0

    def test_data_scientist_dropped(self):
        jobs = [make_job(title="Data Scientist")]
        result = pre_filter(jobs)
        assert len(result) == 0

    def test_intern_dropped(self):
        jobs = [make_job(title="Java Intern")]
        result = pre_filter(jobs)
        assert len(result) == 0

    def test_too_junior_experience_dropped(self):
        jobs = [make_job(title="Java Developer", description="0-1 year experience required")]
        result = pre_filter(jobs)
        assert len(result) == 0

    def test_too_senior_experience_dropped(self):
        jobs = [make_job(title="Java Developer", description="12+ years experience required")]
        result = pre_filter(jobs)
        assert len(result) == 0

    def test_relevant_keyword_in_description_kept(self):
        # Title doesn't have keyword but description does
        jobs = [make_job(title="Software Engineer", description="Java Spring Boot microservices")]
        result = pre_filter(jobs)
        assert len(result) == 1

    def test_no_relevant_keyword_dropped(self):
        jobs = [make_job(title="Product Manager", description="Manage product roadmap")]
        result = pre_filter(jobs)
        assert len(result) == 0

    def test_empty_list_returns_empty(self):
        assert pre_filter([]) == []

    def test_multiple_jobs_filtered_correctly(self):
        jobs = [
            make_job(id="1", title="Java Backend Developer"),
            make_job(id="2", title="React Frontend Developer"),
            make_job(id="3", title="Spring Boot Engineer"),
            make_job(id="4", title="Data Analyst"),
        ]
        result = pre_filter(jobs)
        assert len(result) == 2
        titles = [j["title"] for j in result]
        assert "Java Backend Developer" in titles
        assert "Spring Boot Engineer" in titles

    def test_devops_dropped(self):
        jobs = [make_job(title="DevOps Engineer")]
        result = pre_filter(jobs)
        assert len(result) == 0

    def test_android_dropped(self):
        jobs = [make_job(title="Android Developer")]
        result = pre_filter(jobs)
        assert len(result) == 0

    def test_backend_in_title_kept(self):
        jobs = [make_job(title="Backend Engineer")]
        result = pre_filter(jobs)
        assert len(result) == 1

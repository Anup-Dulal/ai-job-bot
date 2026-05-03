"""
tests/test_apply_agent.py — Tests for apply_agent.py
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apply_agent import ApplyAgent, _get_field_answer, run_apply_agent


def sample_job(**kwargs) -> dict:
    defaults = {
        "id": "naukri_123",
        "title": "Java Backend Developer",
        "company": "Infosys",
        "location": "Noida",
        "link": "https://www.naukri.com/job-listings/java-backend-developer-infosys-123",
        "source": "Naukri",
        "description": "Spring Boot microservices REST API",
    }
    defaults.update(kwargs)
    return defaults


def sample_packet(**kwargs) -> dict:
    defaults = {
        "cover_letter": "Dear Hiring Manager, I am excited to apply...",
        "tailored_resume_path": "/tmp/resume-infosys-java.pdf",
        "tailored_resume": {"summary": "Java developer", "skills": ["Java", "Spring Boot"]},
    }
    defaults.update(kwargs)
    return defaults


# ─── _get_field_answer ────────────────────────────────────────────────────────

class TestGetFieldAnswer:
    def test_name_field(self):
        answer = _get_field_answer("Full Name", sample_job())
        assert answer  # should return profile name

    def test_email_field(self):
        answer = _get_field_answer("Email Address", sample_job())
        assert "@" in answer or answer == ""  # email or empty if not configured

    def test_phone_field(self):
        answer = _get_field_answer("Phone Number", sample_job())
        assert isinstance(answer, str)

    def test_experience_field(self):
        answer = _get_field_answer("Years of Experience", sample_job())
        assert answer.isdigit() or answer == ""

    def test_notice_period_field(self):
        answer = _get_field_answer("Notice Period", sample_job())
        assert isinstance(answer, str)

    def test_expected_ctc_field(self):
        answer = _get_field_answer("Expected CTC", sample_job())
        assert isinstance(answer, str)

    def test_cover_letter_field(self):
        answer = _get_field_answer("Cover Letter", sample_job(), cover_letter="My cover letter text")
        assert "cover letter" in answer.lower() or "My cover" in answer

    def test_unknown_field_returns_string(self):
        with patch("agent.JobApplicationAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.answer_form_question.return_value = "Some answer"
            mock_agent_cls.return_value = mock_agent
            answer = _get_field_answer("Some unknown question", sample_job())
        assert isinstance(answer, str)


# ─── ApplyAgent ───────────────────────────────────────────────────────────────

class TestApplyAgent:
    def test_playwright_unavailable_returns_correct_status(self):
        with patch("apply_agent._is_playwright_available", return_value=False):
            agent = ApplyAgent()
            result = agent.apply(sample_job(), sample_packet())
        assert result["status"] == "playwright_unavailable"
        assert "manually" in result["message"].lower()

    def test_no_apply_url_returns_error(self):
        with patch("apply_agent._is_playwright_available", return_value=True):
            agent = ApplyAgent()
            result = agent.apply(sample_job(link=""), sample_packet())
        assert result["status"] == "error"

    def test_unsupported_source_returns_error(self):
        with patch("apply_agent._is_playwright_available", return_value=True):
            agent = ApplyAgent()
            result = agent.apply(sample_job(source="Indeed"), sample_packet())
        assert result["status"] == "error"
        assert "manually" in result["message"].lower()

    def test_naukri_no_session_no_credentials_returns_error(self):
        with patch("apply_agent._is_playwright_available", return_value=True):
            with patch("naukri_playwright._load_session", return_value=None):
                with patch.dict(os.environ, {"NAUKRI_EMAIL": "", "NAUKRI_PASSWORD": ""}):
                    agent = ApplyAgent()
                    result = agent._apply_naukri(sample_job(), sample_packet())
        assert result["status"] == "error"
        assert "NAUKRI_EMAIL" in result["message"]

    def test_captcha_detection_returns_captcha_status(self):
        mock_page = MagicMock()
        mock_page.url = "https://www.naukri.com/apply"
        mock_page.query_selector.side_effect = lambda sel: MagicMock() if "recaptcha" in sel else None

        agent = ApplyAgent()
        assert agent._has_captcha(mock_page) is True

    def test_no_captcha_returns_false(self):
        mock_page = MagicMock()
        mock_page.query_selector.return_value = None

        agent = ApplyAgent()
        assert agent._has_captcha(mock_page) is False

    def test_get_field_label_uses_aria_label(self):
        mock_element = MagicMock()
        mock_element.get_attribute.side_effect = lambda attr: "Full Name" if attr == "aria-label" else None
        mock_page = MagicMock()

        agent = ApplyAgent()
        label = agent._get_field_label(mock_page, mock_element)
        assert label == "Full Name"

    def test_get_field_label_uses_placeholder(self):
        mock_element = MagicMock()
        mock_element.get_attribute.side_effect = lambda attr: (
            None if attr == "aria-label" else
            "Enter your email" if attr == "placeholder" else None
        )
        mock_page = MagicMock()

        agent = ApplyAgent()
        label = agent._get_field_label(mock_page, mock_element)
        assert label == "Enter your email"


# ─── run_apply_agent ──────────────────────────────────────────────────────────

class TestRunApplyAgent:
    def test_sends_telegram_on_ready_to_submit(self):
        with patch("apply_agent.ApplyAgent.apply") as mock_apply:
            mock_apply.return_value = {
                "status": "ready_to_submit",
                "message": "Form filled!",
                "apply_url": "https://naukri.com/job/123",
            }
            with patch("apply_agent.send_telegram") as mock_tg:
                run_apply_agent(sample_job(), sample_packet())
            mock_tg.assert_called_once()
            assert "filled" in mock_tg.call_args[0][0].lower() or "auto" in mock_tg.call_args[0][0].lower()

    def test_sends_telegram_on_captcha(self):
        with patch("apply_agent.ApplyAgent.apply") as mock_apply:
            mock_apply.return_value = {
                "status": "captcha_detected",
                "message": "CAPTCHA found",
                "apply_url": "https://naukri.com/job/123",
            }
            with patch("apply_agent.send_telegram") as mock_tg:
                run_apply_agent(sample_job(), sample_packet())
            mock_tg.assert_called_once()
            assert "CAPTCHA" in mock_tg.call_args[0][0] or "manually" in mock_tg.call_args[0][0].lower()

    def test_sends_telegram_on_error(self):
        with patch("apply_agent.ApplyAgent.apply") as mock_apply:
            mock_apply.return_value = {
                "status": "error",
                "message": "Something went wrong",
                "apply_url": "https://naukri.com/job/123",
            }
            with patch("apply_agent.send_telegram") as mock_tg:
                run_apply_agent(sample_job(), sample_packet())
            mock_tg.assert_called_once()

    def test_returns_result_dict(self):
        expected = {"status": "ready_to_submit", "message": "Done", "apply_url": "https://x.com"}
        with patch("apply_agent.ApplyAgent.apply", return_value=expected):
            with patch("apply_agent.send_telegram"):
                result = run_apply_agent(sample_job(), sample_packet())
        assert result == expected

"""
tests/test_notifier.py — Tests for notifier.py
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notifier import (
    send_telegram,
    send_job_card,
    parse_telegram_command,
    answer_callback_query,
)


def sample_job(**kwargs) -> dict:
    defaults = {
        "id": "li_123456",
        "title": "Java Backend Developer",
        "company": "Infosys",
        "location": "Noida",
        "score": 82,
        "reason": "Strong Spring Boot match",
        "link": "https://linkedin.com/jobs/view/123456",
        "source": "LinkedIn",
        "easy_apply": True,
    }
    defaults.update(kwargs)
    return defaults


# ─── send_telegram ────────────────────────────────────────────────────────────

class TestSendTelegram:
    def test_returns_false_without_token(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "123"}):
            result = send_telegram("test message")
        assert result is False

    def test_returns_false_without_chat_id(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token123", "TELEGRAM_CHAT_ID": ""}):
            result = send_telegram("test message")
        assert result is False

    def test_sends_message_successfully(self):
        mock_resp = MagicMock()
        mock_resp.is_success = True

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token123", "TELEGRAM_CHAT_ID": "456"}):
            with patch("notifier.httpx.post", return_value=mock_resp) as mock_post:
                result = send_telegram("Hello!")

        assert result is True
        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        assert payload["text"] == "Hello!"
        assert payload["chat_id"] == "456"

    def test_returns_false_on_http_error(self):
        mock_resp = MagicMock()
        mock_resp.is_success = False
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token123", "TELEGRAM_CHAT_ID": "456"}):
            with patch("notifier.httpx.post", return_value=mock_resp):
                result = send_telegram("Hello!")

        assert result is False

    def test_returns_false_on_exception(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token123", "TELEGRAM_CHAT_ID": "456"}):
            with patch("notifier.httpx.post", side_effect=Exception("Network error")):
                result = send_telegram("Hello!")

        assert result is False


# ─── send_job_card ────────────────────────────────────────────────────────────

class TestSendJobCard:
    def test_sends_inline_keyboard(self):
        mock_resp = MagicMock()
        mock_resp.is_success = True
        sent_payload = {}

        def capture_post(url, json=None, **kwargs):
            sent_payload.update(json or {})
            return mock_resp

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}):
            with patch("notifier.httpx.post", side_effect=capture_post):
                send_job_card(sample_job())

        assert "reply_markup" in sent_payload
        assert "inline_keyboard" in sent_payload["reply_markup"]

    def test_inline_keyboard_has_apply_reject_skip(self):
        mock_resp = MagicMock()
        mock_resp.is_success = True
        sent_payload = {}

        def capture_post(url, json=None, **kwargs):
            sent_payload.update(json or {})
            return mock_resp

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}):
            with patch("notifier.httpx.post", side_effect=capture_post):
                send_job_card(sample_job())

        buttons = sent_payload["reply_markup"]["inline_keyboard"]
        row1_texts = [b["text"] for b in buttons[0]]
        assert any("Apply" in t for t in row1_texts)
        assert any("Reject" in t for t in row1_texts)
        assert any("Skip" in t for t in row1_texts)

    def test_callback_data_contains_job_id(self):
        mock_resp = MagicMock()
        mock_resp.is_success = True
        sent_payload = {}

        def capture_post(url, json=None, **kwargs):
            sent_payload.update(json or {})
            return mock_resp

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}):
            with patch("notifier.httpx.post", side_effect=capture_post):
                send_job_card(sample_job(id="li_999"))

        buttons = sent_payload["reply_markup"]["inline_keyboard"]
        all_callbacks = [b["callback_data"] for row in buttons for b in row]
        assert any("li_999" in cb for cb in all_callbacks)

    def test_high_score_shows_fire_emoji(self):
        mock_resp = MagicMock()
        mock_resp.is_success = True
        sent_payload = {}

        def capture_post(url, json=None, **kwargs):
            sent_payload.update(json or {})
            return mock_resp

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}):
            with patch("notifier.httpx.post", side_effect=capture_post):
                send_job_card(sample_job(score=85))

        assert "🔥" in sent_payload["text"]

    def test_naukri_badge_shown(self):
        mock_resp = MagicMock()
        mock_resp.is_success = True
        sent_payload = {}

        def capture_post(url, json=None, **kwargs):
            sent_payload.update(json or {})
            return mock_resp

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}):
            with patch("notifier.httpx.post", side_effect=capture_post):
                send_job_card(sample_job(source="Naukri"))

        assert "🇮🇳" in sent_payload["text"]

    def test_linkedin_easy_apply_badge_shown(self):
        mock_resp = MagicMock()
        mock_resp.is_success = True
        sent_payload = {}

        def capture_post(url, json=None, **kwargs):
            sent_payload.update(json or {})
            return mock_resp

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "123"}):
            with patch("notifier.httpx.post", side_effect=capture_post):
                send_job_card(sample_job(source="LinkedIn", easy_apply=True))

        assert "⚡" in sent_payload["text"]


# ─── parse_telegram_command ───────────────────────────────────────────────────

class TestParseTelegramCommand:
    def test_parses_apply_text_command(self):
        update = {"message": {"text": "APPLY li_123456", "chat": {"id": "1"}}}
        result = parse_telegram_command(update)
        assert result["action"] == "APPLY"
        assert result["job_id"] == "li_123456"
        assert result["is_callback"] is False

    def test_parses_reject_text_command(self):
        update = {"message": {"text": "REJECT naukri_789", "chat": {"id": "1"}}}
        result = parse_telegram_command(update)
        assert result["action"] == "REJECT"
        assert result["job_id"] == "naukri_789"

    def test_parses_skip_text_command(self):
        update = {"message": {"text": "SKIP li_abc", "chat": {"id": "1"}}}
        result = parse_telegram_command(update)
        assert result["action"] == "SKIP"

    def test_case_insensitive_text_command(self):
        update = {"message": {"text": "apply li_123", "chat": {"id": "1"}}}
        result = parse_telegram_command(update)
        assert result["action"] == "APPLY"

    def test_invalid_text_returns_none(self):
        update = {"message": {"text": "hello world", "chat": {"id": "1"}}}
        assert parse_telegram_command(update) is None

    def test_empty_text_returns_none(self):
        update = {"message": {"text": "", "chat": {"id": "1"}}}
        assert parse_telegram_command(update) is None

    def test_parses_inline_apply_callback(self):
        update = {
            "callback_query": {
                "id": "cb_001",
                "data": "apply_li_123456",
                "message": {"chat": {"id": "1"}},
            }
        }
        result = parse_telegram_command(update)
        assert result["action"] == "APPLY"
        assert result["job_id"] == "li_123456"
        assert result["is_callback"] is True
        assert result["callback_query_id"] == "cb_001"

    def test_parses_inline_reject_callback(self):
        update = {
            "callback_query": {
                "id": "cb_002",
                "data": "reject_naukri_pw_java_noida_0",
                "message": {"chat": {"id": "1"}},
            }
        }
        result = parse_telegram_command(update)
        assert result["action"] == "REJECT"
        assert "naukri" in result["job_id"]

    def test_parses_resume_callback(self):
        update = {
            "callback_query": {
                "id": "cb_003",
                "data": "resume_li_999",
                "message": {"chat": {"id": "1"}},
            }
        }
        result = parse_telegram_command(update)
        assert result["action"] == "RESUME"
        assert result["job_id"] == "li_999"

    def test_parses_qa_callback(self):
        update = {
            "callback_query": {
                "id": "cb_004",
                "data": "qa_li_888",
                "message": {"chat": {"id": "1"}},
            }
        }
        result = parse_telegram_command(update)
        assert result["action"] == "QA"

    def test_invalid_callback_returns_none(self):
        update = {
            "callback_query": {
                "id": "cb_005",
                "data": "unknown_action_123",
                "message": {"chat": {"id": "1"}},
            }
        }
        assert parse_telegram_command(update) is None

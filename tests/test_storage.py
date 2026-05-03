"""
tests/test_storage.py — Tests for storage.py (SQLite persistence)
Uses a temporary in-memory database for isolation.
"""

import os
import sys
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    """Redirect DB to a temp file for each test."""
    db_path = tmp_path / "test_job_bot.db"
    with patch("storage.DB_PATH", db_path):
        import storage
        storage.init_db()
        yield db_path


from storage import (
    init_db,
    upsert_jobs,
    get_job,
    mark_notified,
    set_action,
    get_action,
    log_run,
    recent_runs,
    list_pending_actions,
)


def sample_job(job_id="test_1", **kwargs) -> dict:
    defaults = {
        "id": job_id,
        "title": "Java Backend Developer",
        "company": "Infosys",
        "location": "Noida",
        "description": "Spring Boot microservices",
        "skills": ["Java", "Spring Boot"],
        "experience": "3-5 years",
        "link": "https://example.com/job/1",
        "source": "Naukri",
        "days_ago": 2,
        "score": 75,
        "reason": "Good match",
        "decision": "APPLY",
    }
    defaults.update(kwargs)
    return defaults


# ─── upsert_jobs / get_job ────────────────────────────────────────────────────

class TestUpsertAndGetJob:
    def test_insert_and_retrieve(self):
        upsert_jobs([sample_job()])
        job = get_job("test_1")
        assert job is not None
        assert job["title"] == "Java Backend Developer"
        assert job["company"] == "Infosys"

    def test_get_nonexistent_returns_none(self):
        assert get_job("nonexistent_id") is None

    def test_upsert_updates_existing(self):
        upsert_jobs([sample_job()])
        upsert_jobs([sample_job(title="Senior Java Developer")])
        job = get_job("test_1")
        assert job["title"] == "Senior Java Developer"

    def test_skills_stored_as_list(self):
        upsert_jobs([sample_job(skills=["Java", "Spring Boot", "AWS"])])
        job = get_job("test_1")
        assert isinstance(job["skills"], list)
        assert "Java" in job["skills"]

    def test_multiple_jobs_inserted(self):
        jobs = [sample_job(f"job_{i}") for i in range(5)]
        upsert_jobs(jobs)
        for i in range(5):
            assert get_job(f"job_{i}") is not None

    def test_score_preserved_on_upsert_without_score(self):
        upsert_jobs([sample_job(score=85)])
        # Upsert without score — should keep existing score
        upsert_jobs([sample_job(score=None)])
        job = get_job("test_1")
        assert job["score"] == 85

    def test_empty_list_does_nothing(self):
        upsert_jobs([])  # should not raise


# ─── mark_notified ────────────────────────────────────────────────────────────

class TestMarkNotified:
    def test_sets_notified_at(self):
        upsert_jobs([sample_job()])
        mark_notified(["test_1"])
        job = get_job("test_1")
        assert job["notified_at"] is not None

    def test_empty_list_does_nothing(self):
        mark_notified([])  # should not raise

    def test_multiple_jobs_notified(self):
        upsert_jobs([sample_job("j1"), sample_job("j2")])
        mark_notified(["j1", "j2"])
        assert get_job("j1")["notified_at"] is not None
        assert get_job("j2")["notified_at"] is not None


# ─── set_action / get_action ──────────────────────────────────────────────────

class TestSetAndGetAction:
    def test_set_and_get_apply_action(self):
        upsert_jobs([sample_job()])
        packet = {"cover_letter": "Dear Hiring Manager...", "skills": ["Java"]}
        set_action("test_1", "APPLY", packet)
        action = get_action("test_1")
        assert action["action"] == "APPLY"
        assert action["application_packet"]["cover_letter"] == "Dear Hiring Manager..."

    def test_set_reject_action(self):
        upsert_jobs([sample_job()])
        set_action("test_1", "REJECT", None)
        action = get_action("test_1")
        assert action["action"] == "REJECT"
        assert action["application_packet"] is None

    def test_get_action_nonexistent_returns_none(self):
        assert get_action("nonexistent") is None

    def test_update_existing_action(self):
        upsert_jobs([sample_job()])
        set_action("test_1", "SKIP", None)
        set_action("test_1", "APPLY", {"resume": "tailored"})
        action = get_action("test_1")
        assert action["action"] == "APPLY"


# ─── log_run / recent_runs ────────────────────────────────────────────────────

class TestPipelineRuns:
    def test_log_and_retrieve_run(self):
        log_run(fetched_count=50, ranked_count=30, notified_count=5, notes="Test run")
        runs = recent_runs(limit=1)
        assert len(runs) == 1
        assert runs[0]["fetched_count"] == 50
        assert runs[0]["ranked_count"] == 30
        assert runs[0]["notified_count"] == 5
        assert runs[0]["notes"] == "Test run"

    def test_recent_runs_ordered_newest_first(self):
        log_run(10, 5, 2, "run 1")
        log_run(20, 10, 3, "run 2")
        runs = recent_runs(limit=2)
        assert runs[0]["notes"] == "run 2"
        assert runs[1]["notes"] == "run 1"

    def test_limit_respected(self):
        for i in range(5):
            log_run(i, i, i, f"run {i}")
        runs = recent_runs(limit=3)
        assert len(runs) == 3

    def test_empty_notes_allowed(self):
        log_run(10, 5, 2)
        runs = recent_runs(1)
        assert runs[0]["notes"] == ""


# ─── list_pending_actions ─────────────────────────────────────────────────────

class TestListPendingActions:
    def test_notified_job_without_action_is_pending(self):
        upsert_jobs([sample_job()])
        mark_notified(["test_1"])
        pending = list_pending_actions()
        assert any(p["job_id"] == "test_1" for p in pending)

    def test_applied_job_not_pending(self):
        upsert_jobs([sample_job()])
        mark_notified(["test_1"])
        set_action("test_1", "APPLY", None)
        pending = list_pending_actions()
        assert not any(p["job_id"] == "test_1" for p in pending)

    def test_rejected_job_not_pending(self):
        upsert_jobs([sample_job()])
        mark_notified(["test_1"])
        set_action("test_1", "REJECT", None)
        pending = list_pending_actions()
        assert not any(p["job_id"] == "test_1" for p in pending)

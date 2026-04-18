"""
storage.py — SQLite persistence for jobs, decisions, and pipeline runs.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "job_bot.db"


def _now_iso() -> str:
    return datetime.now().isoformat()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT,
                description TEXT,
                skills_json TEXT,
                experience TEXT,
                link TEXT,
                source TEXT,
                days_ago INTEGER DEFAULT 30,
                score INTEGER,
                reason TEXT,
                decision TEXT,
                notified_at TEXT,
                last_seen_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS actions (
                job_id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                application_packet_json TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(job_id)
            );

            CREATE TABLE IF NOT EXISTS pipeline_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                fetched_count INTEGER NOT NULL,
                ranked_count INTEGER NOT NULL,
                notified_count INTEGER NOT NULL,
                notes TEXT
            );
            """
        )


def upsert_jobs(jobs: Iterable[dict]) -> None:
    now = _now_iso()
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO jobs (
                job_id, title, company, location, description, skills_json, experience,
                link, source, days_ago, score, reason, decision, notified_at, last_seen_at
            ) VALUES (
                :id, :title, :company, :location, :description, :skills_json, :experience,
                :link, :source, :days_ago, :score, :reason, :decision, :notified_at, :last_seen_at
            )
            ON CONFLICT(job_id) DO UPDATE SET
                title=excluded.title,
                company=excluded.company,
                location=excluded.location,
                description=excluded.description,
                skills_json=excluded.skills_json,
                experience=excluded.experience,
                link=excluded.link,
                source=excluded.source,
                days_ago=excluded.days_ago,
                score=COALESCE(excluded.score, jobs.score),
                reason=COALESCE(excluded.reason, jobs.reason),
                decision=COALESCE(excluded.decision, jobs.decision),
                last_seen_at=excluded.last_seen_at
            """,
            [
                {
                    "id": job["id"],
                    "title": job.get("title", ""),
                    "company": job.get("company", ""),
                    "location": job.get("location", ""),
                    "description": job.get("description", ""),
                    "skills_json": json.dumps(job.get("skills", [])),
                    "experience": job.get("experience", ""),
                    "link": job.get("link", ""),
                    "source": job.get("source", ""),
                    "days_ago": job.get("days_ago", 30),
                    "score": job.get("score"),
                    "reason": job.get("reason"),
                    "decision": job.get("decision"),
                    "notified_at": job.get("notified_at"),
                    "last_seen_at": now,
                }
                for job in jobs
            ],
        )


def mark_notified(job_ids: List[str]) -> None:
    if not job_ids:
        return
    now = _now_iso()
    with get_conn() as conn:
        conn.executemany(
            "UPDATE jobs SET notified_at = ? WHERE job_id = ?",
            [(now, job_id) for job_id in job_ids],
        )


def get_job(job_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return None
        return _row_to_job(row)


def list_pending_actions(limit: int = 50) -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT j.*, a.action, a.updated_at, a.application_packet_json
            FROM jobs j
            LEFT JOIN actions a ON a.job_id = j.job_id
            WHERE COALESCE(a.action, 'PENDING_DECISION') = 'PENDING_DECISION'
            ORDER BY COALESCE(a.updated_at, j.notified_at, j.last_seen_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_joined_row_to_pending(row) for row in rows]


def set_action(job_id: str, action: str, application_packet: Optional[dict]) -> None:
    now = _now_iso()
    payload = json.dumps(application_packet) if application_packet is not None else None
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO actions (job_id, action, application_packet_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                action=excluded.action,
                application_packet_json=excluded.application_packet_json,
                updated_at=excluded.updated_at
            """,
            (job_id, action, payload, now),
        )


def get_action(job_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM actions WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return None
        return {
            "job_id": row["job_id"],
            "action": row["action"],
            "updated_at": row["updated_at"],
            "application_packet": json.loads(row["application_packet_json"])
            if row["application_packet_json"]
            else None,
        }


def log_run(fetched_count: int, ranked_count: int, notified_count: int, notes: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO pipeline_runs (started_at, fetched_count, ranked_count, notified_count, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (_now_iso(), fetched_count, ranked_count, notified_count, notes),
        )


def recent_runs(limit: int = 10) -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM pipeline_runs ORDER BY run_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def _row_to_job(row: sqlite3.Row) -> dict:
    return {
        "id": row["job_id"],
        "title": row["title"],
        "company": row["company"],
        "location": row["location"],
        "description": row["description"],
        "skills": json.loads(row["skills_json"] or "[]"),
        "experience": row["experience"],
        "link": row["link"],
        "source": row["source"],
        "days_ago": row["days_ago"],
        "score": row["score"],
        "reason": row["reason"],
        "decision": row["decision"],
        "notified_at": row["notified_at"],
        "last_seen_at": row["last_seen_at"],
    }


def _joined_row_to_pending(row: sqlite3.Row) -> dict:
    return {
        "job_id": row["job_id"],
        "status": row["action"] or "PENDING_DECISION",
        "updated_at": row["updated_at"] or row["notified_at"] or row["last_seen_at"],
        "job": _row_to_job(row),
        "application_packet": json.loads(row["application_packet_json"])
        if row["application_packet_json"]
        else None,
    }

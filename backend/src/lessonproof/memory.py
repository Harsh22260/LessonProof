"""SQLite memory that persists run outcomes and everything the system learns across runs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from lessonproof.schemas import EvaluationReport

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT UNIQUE NOT NULL,
    topic TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    rubric_version INTEGER NOT NULL,
    usage_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS check_outcomes (
    run_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    check_id TEXT NOT NULL,
    passed INTEGER NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS guidelines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    check_id TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    origin TEXT NOT NULL,
    after_run_seq INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS judge_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    check_id TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    origin TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    text TEXT NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""

COMPLETED = ("shipped", "rejected")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class CheckStats:
    runs: int = 0
    failures: int = 0
    reasons: list[str] = field(default_factory=list)


@dataclass
class Guideline:
    id: int
    check_id: str
    text: str
    origin: str
    after_run_seq: int


@dataclass
class JudgeNote:
    id: int
    check_id: str
    text: str
    status: str
    origin: str


@dataclass
class Feedback:
    id: int
    run_id: str
    text: str


class MemoryStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def record_run(
        self,
        run_id: str,
        topic: str,
        status: str,
        reports: list[EvaluationReport],
        rubric_version: int,
        usage: dict,
    ) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO runs (run_id, topic, status, attempts, rubric_version, usage_json, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    topic,
                    status,
                    sum(r.attempt > 0 for r in reports),
                    rubric_version,
                    json.dumps(usage),
                    _now(),
                ),
            )
            db.executemany(
                "INSERT INTO check_outcomes VALUES (?, ?, ?, ?, ?)",
                [
                    (run_id, report.attempt, r.check_id, int(r.passed), r.reason)
                    for report in reports
                    for r in report.results
                ],
            )

    def import_shipped_runs(self, runs_dir: Path) -> None:
        """Register approved runs found on disk, so a fresh install can reuse them."""
        with self._connect() as db:
            known = {row["run_id"] for row in db.execute("SELECT run_id FROM runs")}
        for path in sorted(runs_dir.glob("*/trace.json")):
            trace = json.loads(path.read_text(encoding="utf-8"))
            if trace["status"] != "shipped" or trace["run_id"] in known:
                continue
            self.record_run(
                trace["run_id"],
                trace["topic"],
                trace["status"],
                [EvaluationReport.model_validate(a["report"]) for a in trace["attempts"]],
                trace.get("rubric_version", 0),
                trace["usage"],
            )

    def latest_run_seq(self) -> int:
        with self._connect() as db:
            return db.execute("SELECT COALESCE(MAX(seq), 0) FROM runs").fetchone()[0]

    def first_attempt_stats(self, window: int) -> dict[str, CheckStats]:
        placeholders = ",".join("?" * len(COMPLETED))
        query = f"""
            SELECT o.check_id, o.passed, o.reason FROM check_outcomes o
            JOIN (SELECT run_id, seq FROM runs WHERE status IN ({placeholders})
                  ORDER BY seq DESC LIMIT ?) r ON r.run_id = o.run_id
            WHERE o.attempt = (SELECT MIN(x.attempt) FROM check_outcomes x
                               WHERE x.run_id = o.run_id AND x.check_id = o.check_id)
            ORDER BY r.seq
        """
        stats: dict[str, CheckStats] = {}
        with self._connect() as db:
            for row in db.execute(query, (*COMPLETED, window)):
                entry = stats.setdefault(row["check_id"], CheckStats())
                entry.runs += 1
                if not row["passed"]:
                    entry.failures += 1
                    entry.reasons.append(row["reason"])
        return stats

    def first_attempt_rate(
        self, check_id: str, after_seq: int = 0, up_to_seq: int | None = None
    ) -> tuple[int, int]:
        """Returns (failures, runs) on first drafts within a range of runs."""
        query = """
            SELECT COALESCE(SUM(1 - o.passed), 0), COUNT(*) FROM check_outcomes o
            JOIN runs r ON r.run_id = o.run_id
            WHERE o.check_id = ? AND r.seq > ? AND r.seq <= ?
              AND o.attempt = (SELECT MIN(x.attempt) FROM check_outcomes x
                               WHERE x.run_id = o.run_id AND x.check_id = o.check_id)
        """
        upper = up_to_seq if up_to_seq is not None else self.latest_run_seq()
        with self._connect() as db:
            failures, runs = db.execute(query, (check_id, after_seq, upper)).fetchone()
        return failures, runs

    def add_guideline(self, check_id: str, text: str, origin: str) -> int:
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO guidelines (check_id, text, status, origin, after_run_seq, "
                "created_at) VALUES (?, ?, 'active', ?, "
                "(SELECT COALESCE(MAX(seq), 0) FROM runs), ?)",
                (check_id, text, origin, _now()),
            )
            return cursor.lastrowid

    def retire_guideline(self, guideline_id: int) -> None:
        with self._connect() as db:
            db.execute("UPDATE guidelines SET status = 'retired' WHERE id = ?", (guideline_id,))

    def active_guidelines(self, limit: int | None = None) -> list[Guideline]:
        query = (
            "SELECT id, check_id, text, origin, after_run_seq FROM guidelines "
            "WHERE status = 'active' ORDER BY id DESC"
        )
        with self._connect() as db:
            rows = db.execute(query).fetchall()
        guidelines = [Guideline(**dict(row)) for row in rows]
        return guidelines[:limit] if limit else guidelines

    def add_judge_note(self, check_id: str, text: str, origin: str) -> int:
        """New notes start as candidates and only become active if calibration approves them."""
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO judge_notes (check_id, text, status, origin, created_at) "
                "VALUES (?, ?, 'candidate', ?, ?)",
                (check_id, text, origin, _now()),
            )
            return cursor.lastrowid

    def judge_notes(self, status: str) -> list[JudgeNote]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, check_id, text, status, origin FROM judge_notes WHERE status = ?",
                (status,),
            ).fetchall()
        return [JudgeNote(**dict(row)) for row in rows]

    def set_judge_note_status(self, note_ids: list[int], status: str) -> None:
        with self._connect() as db:
            db.executemany(
                "UPDATE judge_notes SET status = ? WHERE id = ?",
                [(status, note_id) for note_id in note_ids],
            )

    def active_notes_by_check(self) -> dict[str, list[str]]:
        notes: dict[str, list[str]] = {}
        for note in self.judge_notes("active"):
            notes.setdefault(note.check_id, []).append(note.text)
        return notes

    def add_feedback(self, run_id: str, text: str) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO feedback (run_id, text, created_at) VALUES (?, ?, ?)",
                (run_id, text, _now()),
            )

    def pending_feedback(self) -> list[Feedback]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, run_id, text FROM feedback WHERE processed = 0"
            ).fetchall()
        return [Feedback(**dict(row)) for row in rows]

    def mark_feedback_processed(self, feedback_id: int) -> None:
        with self._connect() as db:
            db.execute("UPDATE feedback SET processed = 1 WHERE id = ?", (feedback_id,))

    def latest_shipped_run(self, topic: str, rubric_version: int) -> str | None:
        """The newest approved run for a topic under the current rubric, for instant reuse."""
        with self._connect() as db:
            row = db.execute(
                "SELECT run_id FROM runs WHERE LOWER(TRIM(topic)) = LOWER(TRIM(?)) "
                "AND status = 'shipped' AND rubric_version = ? ORDER BY seq DESC LIMIT 1",
                (topic, rubric_version),
            ).fetchone()
        return row["run_id"] if row else None

    def run_history(self) -> list[dict]:
        query = """
            SELECT r.seq, r.run_id, r.topic, r.status, r.attempts, r.usage_json,
                   (SELECT COUNT(DISTINCT o.check_id) FROM check_outcomes o
                    WHERE o.run_id = r.run_id AND o.attempt <= 1 AND o.passed = 0)
                   AS first_draft_failures
            FROM runs r ORDER BY r.seq
        """
        with self._connect() as db:
            return [dict(row) for row in db.execute(query)]

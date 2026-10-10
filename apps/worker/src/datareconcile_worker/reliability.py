from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class RetryableJobError(RuntimeError):
    """A worker operation may be retried without changing its business key."""

    def __init__(self, code: str = "DEPENDENCY_UNAVAILABLE") -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class JobResult:
    key: str
    state: str
    attempt_count: int
    last_error_code: str | None = None
    value: Any = None


class WorkerJobRunner:
    """Durable, at-most-one-active-attempt job execution for synthetic workers.

    The runner deliberately does not perform transfers or other external side
    effects. Callers provide a business-keyed operation (for example, a Store
    import or reconciliation command) which must itself be idempotent.
    """

    def __init__(self, db_path: str, *, max_attempts: int = 3) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.db_path = db_path
        self.max_attempts = max_attempts
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS worker_jobs(
                    job_key TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    last_error_code TEXT,
                    result_json TEXT
                )
                """
            )

    def _conn(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def _result(row: sqlite3.Row) -> JobResult:
        value = json.loads(row["result_json"]) if row["result_json"] else None
        return JobResult(
            key=row["job_key"],
            state=row["state"],
            attempt_count=int(row["attempt_count"]),
            last_error_code=row["last_error_code"],
            value=value,
        )

    def status(self, job_key: str) -> JobResult | None:
        with self._conn() as db:
            row = db.execute("SELECT * FROM worker_jobs WHERE job_key=?", (job_key,)).fetchone()
        return self._result(row) if row else None

    def recover_running(self) -> int:
        """Recover leases left RUNNING by a crashed worker process."""
        with self._conn() as db:
            changed = db.execute(
                """
                UPDATE worker_jobs
                SET state=CASE WHEN attempt_count >= ? THEN 'FAILED_TERMINAL' ELSE 'FAILED_RETRYABLE' END,
                    last_error_code=?
                WHERE state='RUNNING'
                """,
                (self.max_attempts, "WORKER_RESTARTED"),
            ).rowcount
        return int(changed)

    def run(self, job_key: str, operation: Callable[[], Any]) -> JobResult:
        if not job_key.strip():
            raise ValueError("job_key must not be empty")
        with self._conn() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM worker_jobs WHERE job_key=?", (job_key,)).fetchone()
            if row and row["state"] in {"SUCCEEDED", "FAILED_TERMINAL", "RUNNING"}:
                return self._result(row)
            previous_attempts = int(row["attempt_count"]) if row else 0
            attempt = previous_attempts + 1
            if attempt > self.max_attempts:
                db.execute(
                    "UPDATE worker_jobs SET state='FAILED_TERMINAL',last_error_code=? WHERE job_key=?",
                    ("MAX_ATTEMPTS_EXCEEDED", job_key),
                )
                row = db.execute("SELECT * FROM worker_jobs WHERE job_key=?", (job_key,)).fetchone()
                return self._result(row)
            db.execute(
                """
                INSERT INTO worker_jobs(job_key,state,attempt_count,last_error_code,result_json)
                VALUES(?,?,?,?,NULL)
                ON CONFLICT(job_key) DO UPDATE SET state='RUNNING',attempt_count=excluded.attempt_count,last_error_code=NULL
                """,
                (job_key, "RUNNING", attempt, None),
            )

        try:
            value = operation()
        except RetryableJobError as exc:
            state = "FAILED_RETRYABLE" if attempt < self.max_attempts else "FAILED_TERMINAL"
            with self._conn() as db:
                db.execute(
                    "UPDATE worker_jobs SET state=?,last_error_code=? WHERE job_key=? AND state='RUNNING'",
                    (state, exc.code, job_key),
                )
            return self.status(job_key)  # type: ignore[return-value]
        except Exception as exc:
            with self._conn() as db:
                db.execute(
                    "UPDATE worker_jobs SET state='FAILED_TERMINAL',last_error_code=? WHERE job_key=? AND state='RUNNING'",
                    (type(exc).__name__, job_key),
                )
            return self.status(job_key)  # type: ignore[return-value]

        try:
            encoded = json.dumps(value, separators=(",", ":"), allow_nan=False)
            if len(encoded.encode("utf-8")) > 1_048_576:
                raise ValueError("RESULT_SIZE_BUDGET_EXCEEDED")
        except (TypeError, ValueError, OverflowError, UnicodeError):
            # Never convert an invalid result to str(value) and report success.
            # Downstream finance consumers require the original JSON shape.
            with self._conn() as db:
                db.execute(
                    "UPDATE worker_jobs SET state='FAILED_TERMINAL',last_error_code=?,result_json=NULL "
                    "WHERE job_key=? AND state='RUNNING'",
                    ("RESULT_SERIALIZATION_INVALID", job_key),
                )
            return self.status(job_key)  # type: ignore[return-value]
        with self._conn() as db:
            db.execute(
                "UPDATE worker_jobs SET state='SUCCEEDED',last_error_code=NULL,result_json=? WHERE job_key=? AND state='RUNNING'",
                (encoded, job_key),
            )
        return self.status(job_key)  # type: ignore[return-value]

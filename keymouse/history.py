from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class RunRecord:
    id: int
    started_at: str
    ended_at: str | None
    workflow_name: str
    workflow_path: str
    status: str
    total_steps: int
    repeat_count: int
    failure_step: int | None
    error_message: str
    screenshot_path: str
    duration_seconds: float | None


class RunHistoryStore:
    """Small, dependency-free SQLite store for workflow run summaries."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._session() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS run_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    started_timestamp REAL NOT NULL,
                    ended_at TEXT,
                    workflow_name TEXT NOT NULL,
                    workflow_path TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    total_steps INTEGER NOT NULL DEFAULT 0,
                    repeat_count INTEGER NOT NULL DEFAULT 1,
                    failure_step INTEGER,
                    error_message TEXT NOT NULL DEFAULT '',
                    screenshot_path TEXT NOT NULL DEFAULT '',
                    duration_seconds REAL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_run_history_started ON run_history(started_timestamp DESC)"
            )

    def start_run(
        self,
        workflow_name: str,
        workflow_path: str = "",
        total_steps: int = 0,
        repeat_count: int = 1,
    ) -> int:
        now = datetime.now()
        timestamp = time.time()
        with self._session() as connection:
            cursor = connection.execute(
                """
                INSERT INTO run_history (
                    started_at, started_timestamp, workflow_name, workflow_path,
                    status, total_steps, repeat_count
                ) VALUES (?, ?, ?, ?, 'running', ?, ?)
                """,
                (
                    now.isoformat(timespec="seconds"),
                    timestamp,
                    workflow_name,
                    workflow_path,
                    max(0, int(total_steps)),
                    max(1, int(repeat_count)),
                ),
            )
            return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        status: str,
        *,
        failure_step: int | None = None,
        error_message: str = "",
        screenshot_path: str = "",
    ) -> None:
        ended = datetime.now().isoformat(timespec="seconds")
        timestamp = time.time()
        with self._session() as connection:
            connection.execute(
                """
                UPDATE run_history
                SET ended_at = ?, status = ?, failure_step = ?, error_message = ?,
                    screenshot_path = ?,
                    duration_seconds = MAX(0.0, ? - started_timestamp)
                WHERE id = ?
                """,
                (
                    ended,
                    status,
                    failure_step,
                    error_message,
                    screenshot_path,
                    timestamp,
                    int(run_id),
                ),
            )

    def mark_abandoned_runs(self) -> int:
        ended = datetime.now().isoformat(timespec="seconds")
        timestamp = time.time()
        with self._session() as connection:
            cursor = connection.execute(
                """
                UPDATE run_history
                SET ended_at = ?, status = 'interrupted',
                    error_message = CASE
                        WHEN error_message = '' THEN '程序在流程结束前退出'
                        ELSE error_message
                    END,
                    duration_seconds = MAX(0.0, ? - started_timestamp)
                WHERE status = 'running'
                """,
                (ended, timestamp),
            )
            return max(0, int(cursor.rowcount))

    def list_runs(self, limit: int = 200) -> list[RunRecord]:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT id, started_at, ended_at, workflow_name, workflow_path,
                       status, total_steps, repeat_count, failure_step,
                       error_message, screenshot_path, duration_seconds
                FROM run_history
                ORDER BY started_timestamp DESC, id DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [
            RunRecord(
                id=int(row["id"]),
                started_at=str(row["started_at"]),
                ended_at=str(row["ended_at"]) if row["ended_at"] is not None else None,
                workflow_name=str(row["workflow_name"]),
                workflow_path=str(row["workflow_path"]),
                status=str(row["status"]),
                total_steps=int(row["total_steps"]),
                repeat_count=int(row["repeat_count"]),
                failure_step=int(row["failure_step"]) if row["failure_step"] is not None else None,
                error_message=str(row["error_message"]),
                screenshot_path=str(row["screenshot_path"]),
                duration_seconds=(
                    float(row["duration_seconds"]) if row["duration_seconds"] is not None else None
                ),
            )
            for row in rows
        ]

    def delete_runs(self, run_ids: list[int] | tuple[int, ...] | set[int]) -> int:
        """Delete only the selected database records; referenced screenshots are preserved."""
        identifiers = sorted({int(run_id) for run_id in run_ids})
        if not identifiers:
            return 0
        placeholders = ",".join("?" for _ in identifiers)
        with self._session() as connection:
            cursor = connection.execute(
                f"DELETE FROM run_history WHERE id IN ({placeholders})",
                identifiers,
            )
            return max(0, int(cursor.rowcount))

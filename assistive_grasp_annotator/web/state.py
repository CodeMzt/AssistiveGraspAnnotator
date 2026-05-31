"""SQLite-backed web state: datasets, locks, jobs, and audit rows."""

from __future__ import annotations

import json
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass(frozen=True)
class LockRecord:
    id: str
    dataset_id: str
    image_id: str
    image_key: str
    user: str
    token: str
    expires_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "lock_id": self.id,
            "dataset_id": self.dataset_id,
            "image_id": self.image_id,
            "image_key": self.image_key,
            "user": self.user,
            "expires_at": self.expires_at,
        }


class StateStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    root TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS locks (
                    id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    image_id TEXT NOT NULL,
                    image_key TEXT NOT NULL,
                    user TEXT NOT NULL,
                    token TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(dataset_id, image_id)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset_id TEXT NOT NULL,
                    image_id TEXT,
                    user TEXT NOT NULL,
                    action TEXT NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS upload_batches (
                    scope TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    user TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scope, batch_id)
                );
                """
            )

    def register_dataset(self, root: Path, name: str, source: str) -> dict[str, Any]:
        now = iso(utc_now())
        root_str = str(root.resolve())
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM datasets WHERE root = ?", (root_str,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE datasets SET name = ?, source = ?, updated_at = ? WHERE id = ?",
                    (name, source, now, row["id"]),
                )
                return dict(conn.execute("SELECT * FROM datasets WHERE id = ?", (row["id"],)).fetchone())

            dataset_id = uuid.uuid4().hex[:12]
            conn.execute(
                """
                INSERT INTO datasets (id, root, name, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (dataset_id, root_str, name, source, now, now),
            )
            return dict(conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone())

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
            return dict(row) if row else None

    def list_datasets(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM datasets ORDER BY updated_at DESC").fetchall()
            return [dict(row) for row in rows]

    def update_dataset_name(self, dataset_id: str, name: str) -> dict[str, Any] | None:
        now = iso(utc_now())
        with self.connect() as conn:
            conn.execute(
                "UPDATE datasets SET name = ?, updated_at = ? WHERE id = ?",
                (name, now, dataset_id),
            )
            row = conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
            return dict(row) if row else None

    def delete_dataset_state(self, dataset_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
            conn.execute("DELETE FROM locks WHERE dataset_id = ?", (dataset_id,))
            conn.execute("DELETE FROM jobs WHERE dataset_id = ?", (dataset_id,))
            return cur.rowcount > 0

    def log_audit(
        self, dataset_id: str, image_id: str | None, user: str, action: str, detail: dict[str, Any] | None = None
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO audit (dataset_id, image_id, user, action, detail_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (dataset_id, image_id, user, action, json.dumps(detail or {}), iso(utc_now())),
            )

    def start_upload_batch(self, scope: str, batch_id: str, user: str) -> tuple[str, dict[str, Any] | None]:
        now = iso(utc_now())
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM upload_batches WHERE scope = ? AND batch_id = ?",
                (scope, batch_id),
            ).fetchone()
            if row:
                if row["status"] == "done":
                    return "done", json.loads(row["result_json"] or "{}")
                if row["status"] == "running":
                    return "running", None
                conn.execute(
                    """
                    UPDATE upload_batches
                    SET user = ?, status = 'running', result_json = '{}', message = '', updated_at = ?
                    WHERE scope = ? AND batch_id = ?
                    """,
                    (user, now, scope, batch_id),
                )
                return "started", None

            conn.execute(
                """
                INSERT INTO upload_batches (scope, batch_id, user, status, created_at, updated_at)
                VALUES (?, ?, ?, 'running', ?, ?)
                """,
                (scope, batch_id, user, now, now),
            )
            return "started", None

    def finish_upload_batch(
        self,
        scope: str,
        batch_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        message: str = "",
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE upload_batches
                SET status = ?, result_json = ?, message = ?, updated_at = ?
                WHERE scope = ? AND batch_id = ?
                """,
                (status, json.dumps(result or {}), message, iso(utc_now()), scope, batch_id),
            )

    def cleanup_expired_locks(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM locks WHERE expires_at <= ?", (iso(utc_now()),))

    def _row_to_lock(self, row: sqlite3.Row) -> LockRecord:
        return LockRecord(
            id=row["id"],
            dataset_id=row["dataset_id"],
            image_id=row["image_id"],
            image_key=row["image_key"],
            user=row["user"],
            token=row["token"],
            expires_at=row["expires_at"],
        )

    def lock_for_image(self, dataset_id: str, image_id: str) -> LockRecord | None:
        self.cleanup_expired_locks()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM locks WHERE dataset_id = ? AND image_id = ?",
                (dataset_id, image_id),
            ).fetchone()
            return self._row_to_lock(row) if row else None

    def acquire_lock(
        self, dataset_id: str, image_id: str, image_key: str, user: str, ttl_seconds: int
    ) -> tuple[bool, LockRecord]:
        self.cleanup_expired_locks()
        expires_at = iso(utc_now() + timedelta(seconds=ttl_seconds))
        token = secrets.token_urlsafe(24)
        now = iso(utc_now())
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM locks WHERE dataset_id = ? AND image_id = ?",
                (dataset_id, image_id),
            ).fetchone()
            if row and row["user"] != user:
                return (False, self._row_to_lock(row))

            lock_id = row["id"] if row else uuid.uuid4().hex
            if row:
                conn.execute(
                    """
                    UPDATE locks
                    SET user = ?, token = ?, expires_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (user, token, expires_at, now, lock_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO locks (id, dataset_id, image_id, image_key, user, token, expires_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (lock_id, dataset_id, image_id, image_key, user, token, expires_at, now),
                )
            fresh = conn.execute("SELECT * FROM locks WHERE id = ?", (lock_id,)).fetchone()
            return (True, self._row_to_lock(fresh))

    def verify_lock(self, dataset_id: str, image_id: str, lock_id: str, token: str, user: str) -> bool:
        self.cleanup_expired_locks()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM locks
                WHERE id = ? AND dataset_id = ? AND image_id = ? AND token = ? AND user = ?
                """,
                (lock_id, dataset_id, image_id, token, user),
            ).fetchone()
            return row is not None

    def heartbeat_lock(self, lock_id: str, token: str, user: str, ttl_seconds: int) -> LockRecord | None:
        self.cleanup_expired_locks()
        expires_at = iso(utc_now() + timedelta(seconds=ttl_seconds))
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM locks WHERE id = ? AND token = ? AND user = ?",
                (lock_id, token, user),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE locks SET expires_at = ?, updated_at = ? WHERE id = ?",
                (expires_at, iso(utc_now()), lock_id),
            )
            fresh = conn.execute("SELECT * FROM locks WHERE id = ?", (lock_id,)).fetchone()
            return self._row_to_lock(fresh)

    def release_lock(self, lock_id: str, token: str, user: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM locks WHERE id = ? AND token = ? AND user = ?",
                (lock_id, token, user),
            )
            return cur.rowcount > 0

    def release_image_lock_for_user(self, dataset_id: str, image_id: str, user: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM locks WHERE dataset_id = ? AND image_id = ? AND user = ?",
                (dataset_id, image_id, user),
            )
            return cur.rowcount > 0

    def create_job(self, dataset_id: str, job_type: str) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        now = iso(utc_now())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, dataset_id, job_type, status, created_at, updated_at)
                VALUES (?, ?, ?, 'queued', ?, ?)
                """,
                (job_id, dataset_id, job_type, now, now),
            )
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            data = dict(row)
            data["result"] = json.loads(data.pop("result_json") or "{}")
            return data

    def update_job(
        self,
        job_id: str,
        status: str,
        message: str = "",
        result: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, message = ?, result_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, message, json.dumps(result or {}), iso(utc_now()), job_id),
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            data["result"] = json.loads(data.pop("result_json") or "{}")
            return data

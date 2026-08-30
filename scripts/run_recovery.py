#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Crash-safe batch state and completion markers for PaperMiner.

The database is deliberately kept outside the install directory.  SQLite WAL
transactions preserve every document transition even when the GUI or Windows
stops abruptly.  A separate completion marker prevents a partly written
extract directory from being mistaken for a completed document.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


MARKER_NAME = ".paperminer-complete.json"
RESUMABLE_RUN_STATES = ("running", "interrupted", "paused", "cleanup_pending")
TERMINAL_DOCUMENT_STATES = ("complete", "failed", "skipped")
INFLIGHT_DOCUMENT_STATES = ("parsing", "raw_validated", "extracting")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _normalise_source(source_path) -> str:
    return os.path.abspath(os.path.normpath(str(source_path)))


def source_fingerprint(source_path) -> dict | None:
    """Return a cheap identity used to reject stale completion markers."""
    try:
        path = Path(source_path)
        stat = path.stat()
        return {
            "kind": "directory" if path.is_dir() else "file",
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        }
    except OSError:
        return None


def completion_options_signature(options: dict | None) -> str:
    """Hash only options that materially affect a document's final output."""
    options = options if isinstance(options, dict) else {}
    relevant_keys = (
        "extract_text",
        "extract_formula",
        "extract_figures",
        "extract_tables",
        "extract_sections",
        "extract_open_source",
        "backend",
        "llm_model",
        "llm_provider",
    )
    relevant = {key: options.get(key) for key in relevant_keys}
    canonical = json.dumps(
        relevant,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read_completion_marker(extract_directory) -> dict | None:
    marker_path = Path(extract_directory) / MARKER_NAME
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def completion_marker_matches(
    extract_directory,
    options: dict | None,
    source_path=None,
) -> bool:
    payload = read_completion_marker(extract_directory)
    if not payload or payload.get("schema_version") != 1:
        return False
    if payload.get("options_signature") != completion_options_signature(options):
        return False
    if source_path is not None:
        current = source_fingerprint(source_path)
        recorded = payload.get("source_fingerprint")
        if current is None or recorded != current:
            return False
    return True


def write_completion_marker(
    extract_directory,
    *,
    run_id: str | None,
    source_path,
    options: dict | None,
) -> Path:
    """Atomically publish a durable success marker after output validation."""
    directory = Path(extract_directory)
    directory.mkdir(parents=True, exist_ok=True)
    marker_path = directory / MARKER_NAME
    temporary = directory / f"{MARKER_NAME}.{uuid.uuid4().hex}.tmp"
    payload = {
        "schema_version": 1,
        "completed_at": _now(),
        "run_id": str(run_id or ""),
        "source_path": _normalise_source(source_path),
        "source_fingerprint": source_fingerprint(source_path),
        "options_signature": completion_options_signature(options),
    }
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, marker_path)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass
    return marker_path


class RunRecoveryStore:
    """Thread-safe SQLite journal for durable PDF-boundary recovery."""

    def __init__(self, database_path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            str(self.database_path),
            timeout=30,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute("PRAGMA busy_timeout=10000")
            self._create_schema()

    def _create_schema(self):
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    input_directory TEXT NOT NULL,
                    output_directory TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    total_documents INTEGER NOT NULL,
                    recovery_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS documents (
                    run_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    source_path TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    source_fingerprint_json TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    interruptions INTEGER NOT NULL DEFAULT 0,
                    gpu_id INTEGER,
                    raw_directory TEXT,
                    issue_code TEXT,
                    error_text TEXT NOT NULL DEFAULT '',
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, source_path),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_runs_resumable
                    ON runs(status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_documents_status
                    ON documents(run_id, status, ordinal);

                CREATE TABLE IF NOT EXISTS run_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    source_path TEXT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                );
                """
            )

    @staticmethod
    def _decode_run(row) -> dict | None:
        if row is None:
            return None
        payload = dict(row)
        try:
            payload["options"] = json.loads(payload.pop("options_json"))
        except (ValueError, TypeError, json.JSONDecodeError):
            payload["options"] = {}
            payload.pop("options_json", None)
        return payload

    def _event(self, run_id, event_type, source_path=None, payload=None):
        self._connection.execute(
            """
            INSERT INTO run_events
                (run_id, source_path, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_id,
                _normalise_source(source_path) if source_path else None,
                event_type,
                json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
                _now(),
            ),
        )

    def create_run(
        self,
        *,
        mode: str,
        input_directory,
        output_directory,
        options: dict,
        items: Iterable,
    ) -> str:
        item_paths = [_normalise_source(item) for item in items]
        run_id = time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:10]
        now = _now()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO runs (
                    run_id, created_at, updated_at, status, mode,
                    input_directory, output_directory, options_json,
                    total_documents
                ) VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    now,
                    now,
                    str(mode),
                    _normalise_source(input_directory),
                    _normalise_source(output_directory),
                    json.dumps(options or {}, ensure_ascii=False, sort_keys=True),
                    len(item_paths),
                ),
            )
            for ordinal, source in enumerate(item_paths, start=1):
                self._connection.execute(
                    """
                    INSERT INTO documents (
                        run_id, ordinal, source_path, display_name,
                        source_fingerprint_json, status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        run_id,
                        ordinal,
                        source,
                        Path(source).name,
                        json.dumps(source_fingerprint(source), sort_keys=True),
                        now,
                    ),
                )
            self._event(run_id, "run_created", payload={"documents": len(item_paths)})
        return run_id

    def get_run(self, run_id: str) -> dict | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return self._decode_run(row)

    def latest_resumable_run(self) -> dict | None:
        placeholders = ",".join("?" for _ in RESUMABLE_RUN_STATES)
        with self._lock:
            row = self._connection.execute(
                f"""
                SELECT * FROM runs
                WHERE status IN ({placeholders})
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                RESUMABLE_RUN_STATES,
            ).fetchone()
        return self._decode_run(row)

    def list_documents(self, run_id: str) -> list[dict]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM documents
                WHERE run_id = ?
                ORDER BY ordinal, source_path
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def transition_document(
        self,
        run_id: str,
        source_path,
        status: str,
        *,
        increment_attempt: bool = False,
        gpu_id=None,
        raw_directory=None,
        issue_code=None,
        error_text: str = "",
    ):
        source = _normalise_source(source_path)
        now = _now()
        terminal = status in TERMINAL_DOCUMENT_STATES
        starting = status in ("parsing", "extracting")
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE documents
                SET status = ?,
                    attempts = attempts + ?,
                    gpu_id = CASE WHEN ? IS NULL THEN gpu_id ELSE ? END,
                    raw_directory = CASE WHEN ? IS NULL THEN raw_directory ELSE ? END,
                    issue_code = ?,
                    error_text = ?,
                    started_at = CASE
                        WHEN ? = 1 AND started_at IS NULL THEN ?
                        ELSE started_at
                    END,
                    finished_at = CASE WHEN ? = 1 THEN ? ELSE finished_at END,
                    updated_at = ?
                WHERE run_id = ? AND source_path = ?
                """,
                (
                    status,
                    1 if increment_attempt else 0,
                    gpu_id,
                    gpu_id,
                    str(raw_directory) if raw_directory is not None else None,
                    str(raw_directory) if raw_directory is not None else None,
                    issue_code,
                    str(error_text or "")[:4000],
                    1 if starting else 0,
                    now,
                    1 if terminal else 0,
                    now,
                    now,
                    run_id,
                    source,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Document is not registered in run {run_id}: {source}")
            self._connection.execute(
                "UPDATE runs SET updated_at = ? WHERE run_id = ?",
                (now, run_id),
            )
            self._event(
                run_id,
                f"document_{status}",
                source,
                {
                    "gpu_id": gpu_id,
                    "issue_code": issue_code,
                    "raw_directory": str(raw_directory or ""),
                },
            )

    def prepare_resume(self, run_id: str) -> list[dict]:
        """Reset only unfinished documents and return their previous states."""
        terminal_placeholders = ",".join("?" for _ in TERMINAL_DOCUMENT_STATES)
        now = _now()
        with self._lock, self._connection:
            rows = self._connection.execute(
                f"""
                SELECT * FROM documents
                WHERE run_id = ? AND status NOT IN ({terminal_placeholders})
                ORDER BY ordinal, source_path
                """,
                (run_id, *TERMINAL_DOCUMENT_STATES),
            ).fetchall()
            documents = []
            for row in rows:
                item = dict(row)
                previous_status = item["status"]
                item["previous_status"] = previous_status
                documents.append(item)
                self._connection.execute(
                    """
                    UPDATE documents
                    SET status = 'pending',
                        interruptions = interruptions + ?,
                        gpu_id = NULL,
                        issue_code = CASE
                            WHEN ? = 1 THEN 'application_interrupted'
                            ELSE issue_code
                        END,
                        error_text = CASE
                            WHEN ? = 1 THEN 'Recovered after an interrupted application session.'
                            ELSE error_text
                        END,
                        finished_at = NULL,
                        updated_at = ?
                    WHERE run_id = ? AND source_path = ?
                    """,
                    (
                        1 if previous_status in INFLIGHT_DOCUMENT_STATES else 0,
                        1 if previous_status in INFLIGHT_DOCUMENT_STATES else 0,
                        1 if previous_status in INFLIGHT_DOCUMENT_STATES else 0,
                        now,
                        run_id,
                        item["source_path"],
                    ),
                )
            self._connection.execute(
                """
                UPDATE runs
                SET status = 'running', recovery_count = recovery_count + 1,
                    updated_at = ?, last_error = ''
                WHERE run_id = ?
                """,
                (now, run_id),
            )
            self._event(
                run_id,
                "run_resumed",
                payload={"remaining_documents": len(documents)},
            )
        return documents

    def set_run_status(self, run_id: str, status: str, last_error: str = ""):
        now = _now()
        completed_at = now if status in ("completed", "abandoned") else None
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE runs
                SET status = ?, updated_at = ?, completed_at = ?, last_error = ?
                WHERE run_id = ?
                """,
                (status, now, completed_at, str(last_error or "")[:4000], run_id),
            )
            self._event(run_id, f"run_{status}", payload={"error": last_error or ""})

    def summary(self, run_id: str) -> dict:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM documents WHERE run_id = ? GROUP BY status
                """,
                (run_id,),
            ).fetchall()
        counts = {str(row["status"]): int(row["count"]) for row in rows}
        counts["total"] = sum(counts.values())
        counts["unfinished"] = sum(
            count
            for state, count in counts.items()
            if state not in (*TERMINAL_DOCUMENT_STATES, "total", "unfinished")
        )
        return counts

    def close(self):
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

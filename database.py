"""SQLite database for tracking import history and status."""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Generator


class ImportStatus(str, Enum):
    """Status of an import operation."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ImportRecord:
    """Record of an imported note."""

    id: int | None
    source_file: str
    note_title: str
    note_identifier: str
    status: ImportStatus
    wiki_url: str
    target_space: str
    page_url: str | None
    error_message: str | None
    attachments_count: int
    attachments_uploaded: int
    created_at: datetime
    updated_at: datetime


@dataclass
class ImportSession:
    """Record of an import session."""

    id: int | None
    source_path: str
    wiki_url: str
    target_space: str
    total_notes: int
    completed_notes: int
    failed_notes: int
    skipped_notes: int
    status: ImportStatus
    started_at: datetime
    finished_at: datetime | None


class ImportDatabase:
    """SQLite database for tracking imports."""

    def __init__(self, db_path: Path | str = "evernote_imports.db"):
        """Initialize the database connection."""
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database tables."""
        with self._get_connection() as conn:
            # Use WAL mode for better crash recovery and concurrent access
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS import_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_path TEXT NOT NULL,
                    wiki_url TEXT NOT NULL,
                    target_space TEXT NOT NULL,
                    total_notes INTEGER DEFAULT 0,
                    completed_notes INTEGER DEFAULT 0,
                    failed_notes INTEGER DEFAULT 0,
                    skipped_notes INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    finished_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS import_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    source_file TEXT NOT NULL,
                    note_title TEXT NOT NULL,
                    note_identifier TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    wiki_url TEXT,
                    target_space TEXT,
                    page_url TEXT,
                    error_message TEXT,
                    attachments_count INTEGER DEFAULT 0,
                    attachments_uploaded INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES import_sessions(id)
                );

                CREATE INDEX IF NOT EXISTS idx_records_identifier
                    ON import_records(note_identifier);
                CREATE INDEX IF NOT EXISTS idx_records_session
                    ON import_records(session_id);
                CREATE INDEX IF NOT EXISTS idx_records_status
                    ON import_records(status);
                CREATE INDEX IF NOT EXISTS idx_sessions_status
                    ON import_sessions(status);
            """)

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a database connection with context management."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # Session methods

    def create_session(
        self,
        source_path: str,
        wiki_url: str,
        target_space: str,
        total_notes: int = 0,
    ) -> int:
        """Create a new import session."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO import_sessions
                    (source_path, wiki_url, target_space, total_notes, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (source_path, wiki_url, target_space, total_notes, ImportStatus.IN_PROGRESS.value),
            )
            return cursor.lastrowid or 0

    def get_session(self, session_id: int) -> ImportSession | None:
        """Get a session by ID."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM import_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()

            if row:
                return self._row_to_session(row)
            return None

    def update_session_counts(
        self,
        session_id: int,
        completed: int,
        failed: int,
        skipped: int,
    ) -> None:
        """Update session progress counts."""
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE import_sessions
                SET completed_notes = ?, failed_notes = ?, skipped_notes = ?
                WHERE id = ?
                """,
                (completed, failed, skipped, session_id),
            )

    def finish_session(self, session_id: int, status: ImportStatus) -> None:
        """Mark a session as finished."""
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE import_sessions
                SET status = ?, finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status.value, session_id),
            )

    def get_recent_sessions(self, limit: int = 20) -> list[ImportSession]:
        """Get recent import sessions."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM import_sessions
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            return [self._row_to_session(row) for row in rows]

    def _row_to_session(self, row: sqlite3.Row) -> ImportSession:
        """Convert a database row to ImportSession."""
        return ImportSession(
            id=row["id"],
            source_path=row["source_path"],
            wiki_url=row["wiki_url"],
            target_space=row["target_space"],
            total_notes=row["total_notes"],
            completed_notes=row["completed_notes"],
            failed_notes=row["failed_notes"],
            skipped_notes=row["skipped_notes"],
            status=ImportStatus(row["status"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else datetime.now(),
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        )

    # Record methods

    def create_record(
        self,
        session_id: int,
        source_file: str,
        note_title: str,
        note_identifier: str,
        wiki_url: str,
        target_space: str,
        attachments_count: int = 0,
    ) -> int:
        """Create a new import record."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO import_records
                    (session_id, source_file, note_title, note_identifier,
                     wiki_url, target_space, attachments_count, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    source_file,
                    note_title,
                    note_identifier,
                    wiki_url,
                    target_space,
                    attachments_count,
                    ImportStatus.PENDING.value,
                ),
            )
            return cursor.lastrowid or 0

    def update_record_status(
        self,
        record_id: int,
        status: ImportStatus,
        page_url: str | None = None,
        error_message: str | None = None,
        attachments_uploaded: int = 0,
    ) -> None:
        """Update record status."""
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE import_records
                SET status = ?, page_url = ?, error_message = ?,
                    attachments_uploaded = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status.value, page_url, error_message, attachments_uploaded, record_id),
            )

    def get_record_by_identifier(self, note_identifier: str) -> ImportRecord | None:
        """Get a record by note identifier."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM import_records
                WHERE note_identifier = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (note_identifier,),
            ).fetchone()

            if row:
                return self._row_to_record(row)
            return None

    def get_session_file_summary(self, session_id: int) -> list[dict]:
        """Get per-file breakdown for a session.

        Returns list of dicts with keys: source_file, total, completed, failed, skipped.
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    source_file,
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                    SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) as skipped
                FROM import_records
                WHERE session_id = ?
                GROUP BY source_file
                ORDER BY source_file
                """,
                (session_id,),
            ).fetchall()

            return [
                {
                    "source_file": row["source_file"],
                    "total": row["total"],
                    "completed": row["completed"],
                    "failed": row["failed"],
                    "skipped": row["skipped"],
                }
                for row in rows
            ]

    def get_session_records(
        self,
        session_id: int,
        status: ImportStatus | None = None,
        source_file: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ImportRecord]:
        """Get records for a session, optionally filtered by status and/or source file."""
        with self._get_connection() as conn:
            conditions = ["session_id = ?"]
            params: list = [session_id]

            if status:
                conditions.append("status = ?")
                params.append(status.value)

            if source_file:
                conditions.append("source_file = ?")
                params.append(source_file)

            where_clause = " AND ".join(conditions)
            params.extend([limit, offset])

            rows = conn.execute(
                f"""
                SELECT * FROM import_records
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()

            return [self._row_to_record(row) for row in rows]

    def get_all_records(
        self,
        status: ImportStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ImportRecord]:
        """Get all import records."""
        with self._get_connection() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT * FROM import_records
                    WHERE status = ?
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (status.value, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM import_records
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()

            return [self._row_to_record(row) for row in rows]

    def is_note_imported(self, note_identifier: str, wiki_url: str) -> bool:
        """Check if a note has already been imported to a specific wiki."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT id FROM import_records
                WHERE note_identifier = ? AND wiki_url = ? AND status = ?
                LIMIT 1
                """,
                (note_identifier, wiki_url, ImportStatus.COMPLETED.value),
            ).fetchone()

            return row is not None

    def get_stats(self) -> dict:
        """Get overall import statistics."""
        with self._get_connection() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM import_records"
            ).fetchone()[0]

            completed = conn.execute(
                "SELECT COUNT(*) FROM import_records WHERE status = ?",
                (ImportStatus.COMPLETED.value,),
            ).fetchone()[0]

            failed = conn.execute(
                "SELECT COUNT(*) FROM import_records WHERE status = ?",
                (ImportStatus.FAILED.value,),
            ).fetchone()[0]

            skipped = conn.execute(
                "SELECT COUNT(*) FROM import_records WHERE status = ?",
                (ImportStatus.SKIPPED.value,),
            ).fetchone()[0]

            sessions = conn.execute(
                "SELECT COUNT(*) FROM import_sessions"
            ).fetchone()[0]

            return {
                "total_notes": total,
                "completed": completed,
                "failed": failed,
                "skipped": skipped,
                "total_sessions": sessions,
            }

    def _row_to_record(self, row: sqlite3.Row) -> ImportRecord:
        """Convert a database row to ImportRecord."""
        return ImportRecord(
            id=row["id"],
            source_file=row["source_file"],
            note_title=row["note_title"],
            note_identifier=row["note_identifier"],
            status=ImportStatus(row["status"]),
            wiki_url=row["wiki_url"],
            target_space=row["target_space"],
            page_url=row["page_url"],
            error_message=row["error_message"],
            attachments_count=row["attachments_count"],
            attachments_uploaded=row["attachments_uploaded"],
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else datetime.now(),
        )

    def delete_session(self, session_id: int) -> None:
        """Delete a session and all its records."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM import_records WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM import_sessions WHERE id = ?", (session_id,))

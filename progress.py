"""Progress tracking for resumable imports."""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class NoteStatus(str, Enum):
    """Status of a note in the import process."""

    PENDING = "pending"
    UPLOADED = "uploaded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class NoteProgress:
    """Progress information for a single note."""

    identifier: str  # Unique identifier for the note
    title: str
    status: NoteStatus = NoteStatus.PENDING
    error: str | None = None
    page_url: str | None = None
    uploaded_at: str | None = None
    source_file: str | None = None


@dataclass
class ImportProgress:
    """Overall progress of an import session."""

    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    wiki_url: str = ""
    space: str = ""
    total_notes: int = 0
    notes: dict[str, NoteProgress] = field(default_factory=dict)

    @property
    def uploaded_count(self) -> int:
        """Count of successfully uploaded notes."""
        return sum(1 for n in self.notes.values() if n.status == NoteStatus.UPLOADED)

    @property
    def failed_count(self) -> int:
        """Count of failed notes."""
        return sum(1 for n in self.notes.values() if n.status == NoteStatus.FAILED)

    @property
    def pending_count(self) -> int:
        """Count of pending notes."""
        return sum(1 for n in self.notes.values() if n.status == NoteStatus.PENDING)

    @property
    def skipped_count(self) -> int:
        """Count of skipped notes."""
        return sum(1 for n in self.notes.values() if n.status == NoteStatus.SKIPPED)

    def summary(self) -> str:
        """Get a summary string of the current progress."""
        return (
            f"Progress: {self.uploaded_count} uploaded, "
            f"{self.failed_count} failed, "
            f"{self.skipped_count} skipped, "
            f"{self.pending_count} pending "
            f"(total: {len(self.notes)})"
        )


class ProgressTracker:
    """Tracks and persists import progress to enable resumability."""

    DEFAULT_FILENAME = ".evernote_import_progress.json"

    def __init__(self, state_file: Path | str | None = None):
        """
        Initialize progress tracker.

        Args:
            state_file: Path to the state file. If None, uses default in current directory.
        """
        if state_file is None:
            self.state_file = Path.cwd() / self.DEFAULT_FILENAME
        else:
            self.state_file = Path(state_file)

        self.progress = ImportProgress()

    def load(self) -> bool:
        """
        Load progress from state file.

        Returns:
            True if state was loaded, False if no state file exists.
        """
        if not self.state_file.exists():
            return False

        try:
            with open(self.state_file) as f:
                data = json.load(f)

            self.progress = ImportProgress(
                started_at=data.get("started_at", datetime.now().isoformat()),
                last_updated=data.get("last_updated", datetime.now().isoformat()),
                wiki_url=data.get("wiki_url", ""),
                space=data.get("space", ""),
                total_notes=data.get("total_notes", 0),
            )

            # Load notes
            for note_id, note_data in data.get("notes", {}).items():
                self.progress.notes[note_id] = NoteProgress(
                    identifier=note_data["identifier"],
                    title=note_data["title"],
                    status=NoteStatus(note_data["status"]),
                    error=note_data.get("error"),
                    page_url=note_data.get("page_url"),
                    uploaded_at=note_data.get("uploaded_at"),
                    source_file=note_data.get("source_file"),
                )

            return True

        except (json.JSONDecodeError, KeyError, ValueError):
            # Corrupted state file, start fresh
            self.progress = ImportProgress()
            return False

    def save(self) -> None:
        """Save progress to state file."""
        self.progress.last_updated = datetime.now().isoformat()

        data: dict[str, Any] = {
            "started_at": self.progress.started_at,
            "last_updated": self.progress.last_updated,
            "wiki_url": self.progress.wiki_url,
            "space": self.progress.space,
            "total_notes": self.progress.total_notes,
            "notes": {},
        }

        for note_id, note_progress in self.progress.notes.items():
            data["notes"][note_id] = {
                "identifier": note_progress.identifier,
                "title": note_progress.title,
                "status": note_progress.status.value,
                "error": note_progress.error,
                "page_url": note_progress.page_url,
                "uploaded_at": note_progress.uploaded_at,
                "source_file": note_progress.source_file,
            }

        with open(self.state_file, "w") as f:
            json.dump(data, f, indent=2)

    def reset(self) -> None:
        """Reset progress and delete state file."""
        self.progress = ImportProgress()
        if self.state_file.exists():
            self.state_file.unlink()

    def start_session(self, wiki_url: str, space: str, total_notes: int = 0) -> None:
        """Start a new import session."""
        self.progress.wiki_url = wiki_url
        self.progress.space = space
        self.progress.total_notes = total_notes
        self.save()

    def register_note(
        self,
        identifier: str,
        title: str,
        source_file: str | None = None,
    ) -> None:
        """Register a note for tracking."""
        if identifier not in self.progress.notes:
            self.progress.notes[identifier] = NoteProgress(
                identifier=identifier,
                title=title,
                source_file=source_file,
            )

    def mark_uploaded(
        self,
        identifier: str,
        page_url: str | None = None,
    ) -> None:
        """Mark a note as successfully uploaded."""
        if identifier in self.progress.notes:
            note = self.progress.notes[identifier]
            note.status = NoteStatus.UPLOADED
            note.page_url = page_url
            note.uploaded_at = datetime.now().isoformat()
            self.save()

    def mark_failed(self, identifier: str, error: str) -> None:
        """Mark a note as failed."""
        if identifier in self.progress.notes:
            note = self.progress.notes[identifier]
            note.status = NoteStatus.FAILED
            note.error = error
            self.save()

    def mark_skipped(self, identifier: str, reason: str = "Already exists") -> None:
        """Mark a note as skipped."""
        if identifier in self.progress.notes:
            note = self.progress.notes[identifier]
            note.status = NoteStatus.SKIPPED
            note.error = reason
            self.save()

    def is_processed(self, identifier: str) -> bool:
        """Check if a note has already been processed (uploaded or skipped)."""
        if identifier in self.progress.notes:
            return self.progress.notes[identifier].status in (
                NoteStatus.UPLOADED,
                NoteStatus.SKIPPED,
            )
        return False

    def should_retry(self, identifier: str) -> bool:
        """Check if a note should be retried (failed in previous run)."""
        if identifier in self.progress.notes:
            return self.progress.notes[identifier].status == NoteStatus.FAILED
        return True  # Not seen before, should process

    def get_failed_notes(self) -> list[NoteProgress]:
        """Get list of failed notes."""
        return [n for n in self.progress.notes.values() if n.status == NoteStatus.FAILED]


def generate_note_identifier(title: str, created: datetime | None) -> str:
    """Generate a unique identifier for a note."""
    if created:
        key = f"{title}_{created.isoformat()}"
    else:
        key = title

    # Use a hash to ensure a valid identifier
    return hashlib.sha256(key.encode()).hexdigest()[:16]

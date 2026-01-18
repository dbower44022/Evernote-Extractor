"""Data models for Evernote to XWiki extraction."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Attachment:
    """Represents an attachment/resource from an Evernote note."""

    filename: str
    mime_type: str
    data: bytes
    hash: str  # MD5 hash used by Evernote to reference attachments

    @property
    def is_image(self) -> bool:
        """Check if the attachment is an image."""
        return self.mime_type.startswith("image/")

    @property
    def extension(self) -> str:
        """Get file extension based on mime type."""
        mime_to_ext = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "application/pdf": ".pdf",
            "audio/mpeg": ".mp3",
            "audio/wav": ".wav",
            "video/mp4": ".mp4",
            "text/plain": ".txt",
            "application/msword": ".doc",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "application/vnd.ms-excel": ".xls",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        }
        return mime_to_ext.get(self.mime_type, "")


@dataclass
class Note:
    """Represents an Evernote note."""

    title: str
    content: str  # ENML content
    created: Optional[datetime] = None
    updated: Optional[datetime] = None
    tags: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    source_url: Optional[str] = None
    notebook: Optional[str] = None

    @property
    def identifier(self) -> str:
        """Generate a unique identifier for the note based on title and created date."""
        if self.created:
            return f"{self.title}_{self.created.isoformat()}"
        return self.title

    def get_attachment_by_hash(self, hash_value: str) -> Optional[Attachment]:
        """Find an attachment by its MD5 hash."""
        for attachment in self.attachments:
            if attachment.hash == hash_value:
                return attachment
        return None


@dataclass
class Notebook:
    """Represents an Evernote notebook."""

    name: str
    notes: list[Note] = field(default_factory=list)
    stack: Optional[str] = None  # For stacked notebooks

    @property
    def xwiki_space(self) -> str:
        """Convert notebook name to XWiki space path."""
        # Sanitize name for XWiki
        safe_name = self.name.replace(" ", "").replace("/", "").replace("\\", "")
        if self.stack:
            safe_stack = self.stack.replace(" ", "").replace("/", "").replace("\\", "")
            return f"{safe_stack}.{safe_name}"
        return safe_name


@dataclass
class ConvertedPage:
    """Represents a note converted to XWiki format."""

    title: str
    content: str  # XWiki syntax content
    space: str  # XWiki space path
    tags: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    created: Optional[datetime] = None
    updated: Optional[datetime] = None

    @property
    def page_name(self) -> str:
        """Generate a valid XWiki page name from the title."""
        # Remove/replace invalid characters
        safe_name = self.title.replace("/", "-").replace("\\", "-")
        safe_name = safe_name.replace(":", "-").replace("?", "").replace("*", "")
        safe_name = safe_name.replace('"', "").replace("<", "").replace(">", "")
        safe_name = safe_name.replace("|", "-")
        # Replace spaces with nothing for XWiki convention
        safe_name = safe_name.replace(" ", "")
        # Limit length
        if len(safe_name) > 100:
            safe_name = safe_name[:100]
        return safe_name or "UntitledNote"

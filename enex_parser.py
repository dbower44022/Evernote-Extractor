"""ENEX file parser for Evernote exports."""

import base64
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Iterator

from lxml import etree

from .models import Attachment, Note


def parse_enex_datetime(dt_string: str) -> datetime | None:
    """Parse Evernote datetime format (YYYYMMDDTHHMMSSZ)."""
    if not dt_string:
        return None
    try:
        # Format: 20231215T143022Z
        return datetime.strptime(dt_string, "%Y%m%dT%H%M%SZ")
    except ValueError:
        return None


def parse_resource(resource_elem: etree._Element) -> Attachment | None:
    """Parse a resource element into an Attachment."""
    data_elem = resource_elem.find("data")
    mime_elem = resource_elem.find("mime")
    recognition_elem = resource_elem.find("recognition")
    resource_attrs = resource_elem.find("resource-attributes")

    if data_elem is None or data_elem.text is None:
        return None

    # Decode base64 data
    try:
        data = base64.b64decode(data_elem.text)
    except Exception:
        return None

    # Get MIME type
    mime_type = mime_elem.text if mime_elem is not None and mime_elem.text else "application/octet-stream"

    # Calculate MD5 hash (Evernote uses this to reference attachments in ENML)
    hash_value = hashlib.md5(data).hexdigest()

    # Get filename from attributes or generate from hash
    filename = None
    if resource_attrs is not None:
        filename_elem = resource_attrs.find("file-name")
        if filename_elem is not None and filename_elem.text:
            filename = filename_elem.text

    if not filename:
        # Generate filename from hash and mime type
        ext_map = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "application/pdf": ".pdf",
            "audio/mpeg": ".mp3",
            "audio/wav": ".wav",
            "video/mp4": ".mp4",
            "text/plain": ".txt",
        }
        ext = ext_map.get(mime_type, "")
        filename = f"{hash_value}{ext}"

    return Attachment(
        filename=filename,
        mime_type=mime_type,
        data=data,
        hash=hash_value,
    )


def parse_note(note_elem: etree._Element) -> Note:
    """Parse a note element into a Note object."""
    # Title
    title_elem = note_elem.find("title")
    title = title_elem.text if title_elem is not None and title_elem.text else "Untitled"

    # Content (ENML)
    content_elem = note_elem.find("content")
    content = content_elem.text if content_elem is not None and content_elem.text else ""

    # Dates
    created_elem = note_elem.find("created")
    created = parse_enex_datetime(created_elem.text) if created_elem is not None and created_elem.text else None

    updated_elem = note_elem.find("updated")
    updated = parse_enex_datetime(updated_elem.text) if updated_elem is not None and updated_elem.text else None

    # Tags
    tags = []
    for tag_elem in note_elem.findall("tag"):
        if tag_elem.text:
            tags.append(tag_elem.text)

    # Source URL
    note_attrs = note_elem.find("note-attributes")
    source_url = None
    if note_attrs is not None:
        source_url_elem = note_attrs.find("source-url")
        if source_url_elem is not None and source_url_elem.text:
            source_url = source_url_elem.text

    # Attachments/Resources
    attachments = []
    for resource_elem in note_elem.findall("resource"):
        attachment = parse_resource(resource_elem)
        if attachment:
            attachments.append(attachment)

    return Note(
        title=title,
        content=content,
        created=created,
        updated=updated,
        tags=tags,
        attachments=attachments,
        source_url=source_url,
    )


def parse_enex_file(file_path: Path | str) -> Iterator[Note]:
    """
    Parse an ENEX file and yield Note objects.

    Uses huge_tree parser to handle very large text nodes (e.g., base64 attachments).
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"ENEX file not found: {file_path}")

    # Use huge_tree parser to handle very large text nodes
    parser = etree.XMLParser(huge_tree=True)
    tree = etree.parse(str(file_path), parser)
    root = tree.getroot()

    for note_elem in root.findall("note"):
        yield parse_note(note_elem)
        # Clear the element to free memory after processing
        note_elem.clear()


def parse_enex_directory(directory: Path | str, recursive: bool = True) -> Iterator[tuple[Path, Note]]:
    """
    Parse all ENEX files in a directory (and subdirectories if recursive=True).

    Yields tuples of (file_path, note) for each note found.
    The note.notebook field will contain the relative path including the ENEX filename,
    e.g., "Projects/Archive/old" for /exports/Projects/Archive/old.enex
    """
    directory = Path(directory)

    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    # Find all ENEX files (recursively if specified)
    if recursive:
        enex_files = sorted(directory.rglob("*.enex"))
    else:
        enex_files = sorted(directory.glob("*.enex"))

    for enex_file in enex_files:
        # Calculate relative path from the base directory
        relative_path = enex_file.relative_to(directory)
        # Remove the .enex extension and convert to dot-separated path for XWiki
        # e.g., "Projects/Archive/old.enex" -> "Projects.Archive.old"
        relative_parts = list(relative_path.parent.parts) + [relative_path.stem]
        notebook_path = ".".join(relative_parts) if relative_parts != [relative_path.stem] else relative_path.stem

        for note in parse_enex_file(enex_file):
            # Set the notebook to the full relative path
            note.notebook = notebook_path
            yield (enex_file, note)


def count_notes_in_enex(file_path: Path | str) -> int:
    """Count the number of notes in an ENEX file without fully parsing."""
    file_path = Path(file_path)

    # Use huge_tree parser to handle very large text nodes
    parser = etree.XMLParser(huge_tree=True)
    tree = etree.parse(str(file_path), parser)
    root = tree.getroot()

    return len(root.findall("note"))


def get_note_summaries_from_enex(file_path: Path | str) -> list[dict]:
    """
    Extract lightweight note summaries from an ENEX file.

    Only reads title and created date — skips resource elements entirely,
    so this is much faster than full parsing for large files.

    Returns list of {"title": str, "created": datetime | None} dicts.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"ENEX file not found: {file_path}")

    parser = etree.XMLParser(huge_tree=True)
    tree = etree.parse(str(file_path), parser)
    root = tree.getroot()

    summaries = []
    for note_elem in root.findall("note"):
        title_elem = note_elem.find("title")
        title = title_elem.text if title_elem is not None and title_elem.text else "Untitled"

        created_elem = note_elem.find("created")
        created = parse_enex_datetime(created_elem.text) if created_elem is not None and created_elem.text else None

        summaries.append({"title": title, "created": created})
        note_elem.clear()

    return summaries


def build_enex_inventory(source_path: Path | str) -> tuple[dict[str, list[dict]], int]:
    """
    Build an inventory of all notes across ENEX file(s).

    Args:
        source_path: Path to a single ENEX file or a directory containing ENEX files.

    Returns:
        Tuple of (inventory, grand_total) where inventory maps each ENEX file path
        (as string) to its list of note summaries, and grand_total is the total
        note count across all files.
    """
    source = Path(source_path)
    inventory: dict[str, list[dict]] = {}
    grand_total = 0

    if source.is_file() and source.suffix.lower() == ".enex":
        summaries = get_note_summaries_from_enex(source)
        inventory[str(source)] = summaries
        grand_total = len(summaries)
    elif source.is_dir():
        for enex_file in sorted(source.rglob("*.enex"), key=lambda p: str(p).casefold()):
            summaries = get_note_summaries_from_enex(enex_file)
            inventory[str(enex_file)] = summaries
            grand_total += len(summaries)
    else:
        raise ValueError(f"Source path is not an ENEX file or directory: {source}")

    return inventory, grand_total

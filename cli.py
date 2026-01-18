"""Command-line interface for Evernote to XWiki extractor."""

import os
import sys
from pathlib import Path

import click

from .converter import convert_note
from .enex_parser import count_notes_in_enex, parse_enex_directory, parse_enex_file
from .progress import ProgressTracker, generate_note_identifier
from .xwiki_client import XWikiClient


@click.group()
@click.version_option(version="1.0.0", prog_name="evernote-extractor")
def cli():
    """Evernote to XWiki extraction tool.

    Export notes from Evernote using the desktop app (File → Export),
    then use this tool to import them into XWiki Cloud.
    """
    pass


@cli.command()
@click.argument("source", type=click.Path(exists=True))
@click.option(
    "--wiki-url",
    required=True,
    help="XWiki instance URL (e.g., https://yourwiki.xwiki.cloud)",
)
@click.option(
    "--space",
    default="ImportedNotes",
    help="Target XWiki space for imported notes (default: ImportedNotes)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Parse and convert without uploading to XWiki",
)
@click.option(
    "--resume",
    is_flag=True,
    help="Resume a previous import session",
)
@click.option(
    "--retry-failed",
    is_flag=True,
    help="Retry notes that failed in a previous run",
)
@click.option(
    "--state-file",
    type=click.Path(),
    help="Path to state file for progress tracking",
)
@click.option(
    "--skip-existing",
    is_flag=True,
    help="Skip notes that already exist in XWiki",
)
@click.option(
    "--rate-limit",
    type=float,
    default=0.5,
    help="Delay between API requests in seconds (default: 0.5)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose output",
)
def import_notes(
    source: str,
    wiki_url: str,
    space: str,
    dry_run: bool,
    resume: bool,
    retry_failed: bool,
    state_file: str | None,
    skip_existing: bool,
    rate_limit: float,
    verbose: bool,
):
    """Import Evernote notes from ENEX file(s) to XWiki.

    SOURCE can be a single .enex file or a directory containing multiple .enex files.
    """
    source_path = Path(source)

    # Get credentials from environment
    username = os.environ.get("XWIKI_USERNAME")
    password = os.environ.get("XWIKI_PASSWORD")
    if (not username or not password) and not dry_run:
        click.echo("Error: XWIKI_USERNAME and XWIKI_PASSWORD environment variables are required.", err=True)
        click.echo("Set them with:", err=True)
        click.echo("  export XWIKI_USERNAME='your-username'", err=True)
        click.echo("  export XWIKI_PASSWORD='your-password'", err=True)
        sys.exit(1)

    # Initialize XWiki client
    client = None
    if not dry_run:
        client = XWikiClient(
            wiki_url=wiki_url,
            username=username or "",
            password=password or "",
            rate_limit_delay=rate_limit,
        )

        # Test connection
        click.echo(f"Connecting to {wiki_url}...")
        if not client.test_connection():
            click.echo("Error: Could not connect to XWiki. Check your URL and credentials.", err=True)
            sys.exit(1)
        click.echo("Connected successfully.")

    # Initialize progress tracker
    tracker = ProgressTracker(state_file)

    if resume:
        if tracker.load():
            click.echo(f"Resuming previous session: {tracker.progress.summary()}")
        else:
            click.echo("No previous session found, starting fresh.")

    # Count total notes first (recursively for directories)
    click.echo("Scanning ENEX files...")
    total_notes = 0

    if source_path.is_file():
        total_notes = count_notes_in_enex(source_path)
        click.echo(f"Found {total_notes} notes in {source_path.name}")
    else:
        # Recursively find all ENEX files
        enex_files = list(source_path.rglob("*.enex"))
        for enex_file in enex_files:
            count = count_notes_in_enex(enex_file)
            total_notes += count
            if verbose:
                relative = enex_file.relative_to(source_path)
                click.echo(f"  {relative}: {count} notes")
        click.echo(f"Found {total_notes} notes in {len(enex_files)} files")

    if total_notes == 0:
        click.echo("No notes found to import.")
        return

    # Start tracking session
    tracker.start_session(wiki_url, space, total_notes)

    # Process notes
    uploaded = 0
    failed = 0
    skipped = 0

    if source_path.is_file():
        notes_iter = ((source_path, note) for note in parse_enex_file(source_path))
    else:
        notes_iter = parse_enex_directory(source_path)

    with click.progressbar(
        notes_iter,
        length=total_notes,
        label="Importing notes",
        show_pos=True,
    ) as notes:
        for file_path, note in notes:
            # Generate identifier
            note_id = generate_note_identifier(note.title, note.created)

            # Register note for tracking
            tracker.register_note(
                identifier=note_id,
                title=note.title,
                source_file=str(file_path),
            )

            # Check if already processed
            if resume and tracker.is_processed(note_id):
                if verbose:
                    click.echo(f"\nSkipping (already processed): {note.title}")
                skipped += 1
                continue

            # Check if should retry
            if resume and not retry_failed and not tracker.should_retry(note_id):
                if verbose:
                    click.echo(f"\nSkipping (previously failed): {note.title}")
                skipped += 1
                continue

            # Convert note
            try:
                page = convert_note(note, space)
            except Exception as e:
                tracker.mark_failed(note_id, f"Conversion error: {e}")
                failed += 1
                if verbose:
                    click.echo(f"\nConversion failed: {note.title} - {e}")
                continue

            if dry_run:
                if verbose:
                    click.echo(f"\n[DRY RUN] Would upload: {page.title} to {page.space}/{page.page_name}")
                    click.echo(f"  Content length: {len(page.content)} chars")
                    click.echo(f"  Attachments: {len(page.attachments)}")
                    click.echo(f"  Tags: {page.tags}")
                tracker.mark_uploaded(note_id, f"[dry-run] {page.space}/{page.page_name}")
                uploaded += 1
                continue

            # Check if page exists
            if skip_existing and client and client.page_exists(page.space, page.page_name):
                tracker.mark_skipped(note_id, "Page already exists")
                skipped += 1
                if verbose:
                    click.echo(f"\nSkipping (exists): {note.title}")
                continue

            # Upload to XWiki
            if client:
                result = client.create_or_update_page(page, dry_run=False)

                if result.success:
                    tracker.mark_uploaded(note_id, result.page_url)
                    uploaded += 1
                    if verbose:
                        click.echo(f"\nUploaded: {note.title}")
                        if result.attachments_uploaded > 0:
                            click.echo(f"  Attachments: {result.attachments_uploaded} uploaded")
                        if result.attachments_failed > 0:
                            click.echo(f"  Attachments failed: {result.attachments_failed}")
                else:
                    tracker.mark_failed(note_id, result.error or "Unknown error")
                    failed += 1
                    if verbose:
                        click.echo(f"\nFailed: {note.title} - {result.error}")

    # Final summary
    click.echo("\n" + "=" * 50)
    click.echo("Import complete!")
    click.echo(f"  Uploaded: {uploaded}")
    click.echo(f"  Failed: {failed}")
    click.echo(f"  Skipped: {skipped}")

    if failed > 0:
        click.echo(f"\nFailed notes are recorded in: {tracker.state_file}")
        click.echo("Use --retry-failed to retry them.")

    if dry_run:
        click.echo("\n[DRY RUN] No changes were made to XWiki.")


@cli.command()
@click.argument("source", type=click.Path(exists=True))
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output directory for converted files",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose output",
)
def convert(source: str, output: str | None, verbose: bool):
    """Convert ENEX files to XWiki format without uploading.

    Useful for previewing the conversion before importing.
    """
    source_path = Path(source)
    output_path = Path(output) if output else Path.cwd() / "converted"

    output_path.mkdir(parents=True, exist_ok=True)

    click.echo(f"Converting ENEX files to XWiki format...")
    click.echo(f"Output directory: {output_path}")

    converted = 0

    if source_path.is_file():
        notes_iter = parse_enex_file(source_path)
    else:
        notes_iter = (note for _, note in parse_enex_directory(source_path))

    for note in notes_iter:
        try:
            page = convert_note(note)

            # Save converted content
            safe_name = page.page_name[:50]  # Limit filename length
            output_file = output_path / f"{safe_name}.txt"

            # Handle duplicate filenames
            counter = 1
            while output_file.exists():
                output_file = output_path / f"{safe_name}_{counter}.txt"
                counter += 1

            with open(output_file, "w") as f:
                f.write(f"Title: {page.title}\n")
                f.write(f"Space: {page.space}\n")
                f.write(f"Tags: {', '.join(page.tags)}\n")
                f.write(f"Attachments: {len(page.attachments)}\n")
                f.write("=" * 50 + "\n\n")
                f.write(page.content)

            converted += 1
            if verbose:
                click.echo(f"Converted: {note.title} → {output_file.name}")

        except Exception as e:
            click.echo(f"Error converting {note.title}: {e}", err=True)

    click.echo(f"\nConverted {converted} notes to {output_path}")


@cli.command()
@click.option(
    "--state-file",
    type=click.Path(exists=True),
    help="Path to state file",
)
def status(state_file: str | None):
    """Show status of a previous import session."""
    tracker = ProgressTracker(state_file)

    if not tracker.load():
        click.echo("No import session found.")
        return

    p = tracker.progress
    click.echo(f"Import Session Status")
    click.echo("=" * 50)
    click.echo(f"Started: {p.started_at}")
    click.echo(f"Last updated: {p.last_updated}")
    click.echo(f"Wiki URL: {p.wiki_url}")
    click.echo(f"Target space: {p.space}")
    click.echo()
    click.echo(f"Total notes: {len(p.notes)}")
    click.echo(f"  Uploaded: {p.uploaded_count}")
    click.echo(f"  Failed: {p.failed_count}")
    click.echo(f"  Skipped: {p.skipped_count}")
    click.echo(f"  Pending: {p.pending_count}")

    failed = tracker.get_failed_notes()
    if failed:
        click.echo(f"\nFailed notes:")
        for note in failed[:10]:  # Show first 10
            click.echo(f"  - {note.title}: {note.error}")
        if len(failed) > 10:
            click.echo(f"  ... and {len(failed) - 10} more")


@cli.command()
@click.option(
    "--state-file",
    type=click.Path(exists=True),
    help="Path to state file",
)
@click.confirmation_option(prompt="This will delete the progress file. Continue?")
def reset(state_file: str | None):
    """Reset import progress (delete state file)."""
    tracker = ProgressTracker(state_file)
    tracker.reset()
    click.echo("Progress reset.")


def main():
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()

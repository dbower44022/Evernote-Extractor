"""Streamlit UI for Evernote to XWiki extraction tool."""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

# Handle imports for both module and direct execution
try:
    from .converter import convert_note
    from .database import ImportDatabase, ImportStatus
    from .enex_parser import count_notes_in_enex, parse_enex_directory, parse_enex_file
    from .progress import generate_note_identifier
    from .xwiki_client import XWikiClient
    from .evernote_api import (
        EvernoteClient,
        EvernoteCredentials,
        EvernoteOAuth,
        load_token,
        save_token,
        delete_token,
    )
except ImportError:
    # Add parent directory to path for direct execution
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from evernote_extractor.converter import convert_note
    from evernote_extractor.database import ImportDatabase, ImportStatus
    from evernote_extractor.enex_parser import count_notes_in_enex, parse_enex_directory, parse_enex_file
    from evernote_extractor.progress import generate_note_identifier
    from evernote_extractor.xwiki_client import XWikiClient
    from evernote_extractor.evernote_api import (
        EvernoteClient,
        EvernoteCredentials,
        EvernoteOAuth,
        load_token,
        save_token,
        delete_token,
    )

# Page config
st.set_page_config(
    page_title="Evernote to XWiki Importer",
    page_icon="📝",
    layout="wide",
)

# Config file path
CONFIG_PATH = Path.home() / ".evernote_extractor" / "config.json"


def load_config() -> dict:
    """Load saved configuration."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_config(config: dict) -> None:
    """Save configuration to file."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


# Initialize database
@st.cache_resource
def get_database():
    """Get or create database connection."""
    db_path = Path.home() / ".evernote_extractor" / "imports.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return ImportDatabase(db_path)


def main():
    """Main application."""
    st.title("📝 Evernote to XWiki Importer")

    db = get_database()

    # Sidebar navigation
    page = st.sidebar.radio(
        "Navigation",
        ["Import from Evernote", "Import from ENEX Files", "Import History", "Statistics"],
        index=0,
    )

    if page == "Import from Evernote":
        render_evernote_direct_page(db)
    elif page == "Import from ENEX Files":
        render_import_page(db)
    elif page == "Import History":
        render_history_page(db)
    else:
        render_stats_page(db)


def render_evernote_direct_page(db: ImportDatabase):
    """Render the direct Evernote import page."""
    st.header("Import Directly from Evernote")

    # Load config
    config = load_config()

    # Evernote API Configuration
    with st.expander("Evernote API Configuration", expanded=not config.get("evernote_consumer_key")):
        st.markdown("""
        To connect directly to Evernote, you need API credentials.

        **To get credentials:**
        1. Go to [Evernote Developer Portal](https://dev.evernote.com/)
        2. Create a new API Key
        3. Enter your Consumer Key and Secret below
        """)

        col1, col2 = st.columns(2)
        with col1:
            consumer_key = st.text_input(
                "Consumer Key",
                value=config.get("evernote_consumer_key", ""),
                help="Your Evernote API Consumer Key",
            )
        with col2:
            consumer_secret = st.text_input(
                "Consumer Secret",
                value=config.get("evernote_consumer_secret", ""),
                type="password",
                help="Your Evernote API Consumer Secret",
            )

        use_sandbox = st.checkbox(
            "Use Sandbox (for testing)",
            value=config.get("evernote_sandbox", False),
            help="Use Evernote's sandbox environment for testing",
        )

        if st.button("Save Evernote API Settings"):
            config["evernote_consumer_key"] = consumer_key
            config["evernote_consumer_secret"] = consumer_secret
            config["evernote_sandbox"] = use_sandbox
            save_config(config)
            st.success("Evernote API settings saved!")

    # Check if API credentials are configured
    if not config.get("evernote_consumer_key") or not config.get("evernote_consumer_secret"):
        st.warning("Please configure your Evernote API credentials above to continue.")
        return

    # XWiki Configuration
    with st.expander("XWiki Configuration", expanded=True):
        col1, col2 = st.columns(2)

        with col1:
            wiki_url = st.text_input(
                "XWiki URL",
                value=config.get("wiki_url", ""),
                placeholder="https://yourwiki.xwiki.cloud",
            )

        with col2:
            target_space = st.text_input(
                "Target Space",
                value=config.get("target_space", "ImportedNotes"),
            )

        col3, col4 = st.columns(2)

        with col3:
            username = st.text_input(
                "XWiki Username",
                value=config.get("username", ""),
            )

        with col4:
            password = st.text_input(
                "XWiki Password",
                value=config.get("password", ""),
                type="password",
            )

    # Evernote Connection
    st.subheader("Connect to Evernote")

    # Check for existing token
    existing_token = load_token()

    if existing_token:
        st.success("Connected to Evernote (token saved)")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Disconnect from Evernote"):
                delete_token()
                st.rerun()

        with col2:
            if st.button("Test Connection"):
                with st.spinner("Testing connection..."):
                    try:
                        client = EvernoteClient(
                            existing_token,
                            sandbox=config.get("evernote_sandbox", False),
                        )
                        user_info = client.get_user_info()
                        if "error" in user_info:
                            st.error(f"Connection failed: {user_info['error']}")
                            st.info("Your token may have expired. Try disconnecting and reconnecting.")
                        else:
                            st.success(f"Connected as: {user_info.get('username', 'Unknown')}")
                    except Exception as e:
                        st.error(f"Connection failed: {e}")

        # Notebook selection and import
        st.subheader("Select Notebooks to Import")

        try:
            client = EvernoteClient(
                existing_token,
                sandbox=config.get("evernote_sandbox", False),
            )

            with st.spinner("Loading notebooks..."):
                notebooks = client.list_notebooks()

            if not notebooks:
                st.warning("No notebooks found in your Evernote account.")
            else:
                # Group by stack
                stacks: dict[str, list] = {"(No Stack)": []}
                for nb in notebooks:
                    stack_name = nb.stack or "(No Stack)"
                    if stack_name not in stacks:
                        stacks[stack_name] = []
                    stacks[stack_name].append(nb)

                # Display notebooks with checkboxes
                st.write(f"Found {len(notebooks)} notebooks:")

                selected_notebooks = []

                for stack_name, stack_notebooks in sorted(stacks.items()):
                    if stack_name != "(No Stack)":
                        st.markdown(f"**{stack_name}/**")

                    for nb in stack_notebooks:
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            prefix = "    " if stack_name != "(No Stack)" else ""
                            if st.checkbox(
                                f"{prefix}{nb.name} ({nb.note_count} notes)",
                                key=f"nb_{nb.guid}",
                            ):
                                selected_notebooks.append(nb)
                        with col2:
                            st.caption(f"{nb.note_count} notes")

                # Import options
                st.subheader("Import Options")

                rate_limit = st.slider("Rate limit (seconds)", 0.1, 2.0, 0.5, 0.1)

                # Skip options
                st.markdown("**Skip Options**")
                col1, col2 = st.columns(2)
                with col1:
                    skip_existing_db = st.checkbox(
                        "Skip if previously imported (database)",
                        value=True,
                        help="Skip notes that were imported in a previous session (fast, checks local database)",
                        key="evernote_skip_db",
                    )
                with col2:
                    skip_existing_xwiki = st.checkbox(
                        "Skip if exists in XWiki",
                        value=False,
                        help="Skip notes that already exist in XWiki (slower, checks XWiki API for each note)",
                        key="evernote_skip_xwiki",
                    )

                # Import button
                if st.button(
                    "Start Import",
                    disabled=not selected_notebooks or not wiki_url or not username or not password,
                    type="primary",
                ):
                    # Save XWiki config
                    config["wiki_url"] = wiki_url
                    config["target_space"] = target_space
                    config["username"] = username
                    config["password"] = password
                    save_config(config)

                    run_evernote_import(
                        db=db,
                        evernote_client=client,
                        selected_notebooks=selected_notebooks,
                        wiki_url=wiki_url,
                        username=username,
                        password=password,
                        target_space=target_space,
                        skip_existing_db=skip_existing_db,
                        skip_existing_xwiki=skip_existing_xwiki,
                        rate_limit=rate_limit,
                    )

        except Exception as e:
            st.error(f"Error connecting to Evernote: {e}")
            st.info("Try disconnecting and reconnecting to Evernote.")

    else:
        st.info("Click the button below to connect to your Evernote account.")

        if st.button("Connect to Evernote", type="primary"):
            with st.spinner("Opening browser for authentication..."):
                try:
                    credentials = EvernoteCredentials(
                        consumer_key=config.get("evernote_consumer_key", ""),
                        consumer_secret=config.get("evernote_consumer_secret", ""),
                        sandbox=config.get("evernote_sandbox", False),
                    )

                    oauth = EvernoteOAuth(credentials)
                    token = oauth.authenticate(open_browser=True)

                    if token:
                        save_token(token)
                        st.success("Successfully connected to Evernote!")
                        st.rerun()
                    else:
                        st.error("Authentication failed or was cancelled.")

                except Exception as e:
                    st.error(f"Authentication error: {e}")


def run_evernote_import(
    db: ImportDatabase,
    evernote_client: EvernoteClient,
    selected_notebooks: list,
    wiki_url: str,
    username: str,
    password: str,
    target_space: str,
    skip_existing_db: bool,
    skip_existing_xwiki: bool,
    rate_limit: float,
):
    """Run import from Evernote to XWiki."""
    # Calculate total notes
    total_notes = sum(nb.note_count for nb in selected_notebooks)

    if total_notes == 0:
        st.warning("Selected notebooks contain no notes.")
        return

    st.info(f"Importing {total_notes} notes from {len(selected_notebooks)} notebooks")

    # Create session
    session_id = db.create_session(
        source_path="evernote://direct",
        wiki_url=wiki_url,
        target_space=target_space,
        total_notes=total_notes,
    )

    # Initialize XWiki client
    xwiki_client = XWikiClient(
        wiki_url=wiki_url,
        username=username,
        password=password,
        rate_limit_delay=rate_limit,
    )

    # Test XWiki connection
    with st.spinner("Connecting to XWiki..."):
        if not xwiki_client.test_connection():
            st.error("Could not connect to XWiki. Please check your credentials.")
            db.finish_session(session_id, ImportStatus.FAILED)
            return

    st.success("Connected to XWiki!")

    # Progress tracking
    progress_bar = st.progress(0, text="Starting import...")
    status_container = st.empty()
    log_container = st.container()

    completed = 0
    failed = 0
    skipped = 0
    processed = 0

    # Process each notebook
    for notebook in selected_notebooks:
        with log_container:
            st.markdown(f"**Importing notebook: {notebook.name}**")

        # Build the notebook path for XWiki space
        if notebook.stack:
            notebook_path = f"{notebook.stack}.{notebook.name}".replace(" ", "")
        else:
            notebook_path = notebook.name.replace(" ", "")

        # Download and import notes from this notebook
        def progress_callback(current: int, total: int, title: str):
            nonlocal processed
            processed = completed + failed + skipped + current
            progress = processed / total_notes if total_notes > 0 else 0
            progress_bar.progress(progress, text=f"Processing: {title[:50]}...")

        for note in evernote_client.get_notes_from_notebook(
            notebook.guid,
            notebook_name=notebook_path,
            progress_callback=progress_callback,
        ):
            from .progress import generate_note_identifier

            note_id = generate_note_identifier(note.title, note.created)

            # Create record
            record_id = db.create_record(
                session_id=session_id,
                source_file=f"evernote://{notebook.name}",
                note_title=note.title,
                note_identifier=note_id,
                wiki_url=wiki_url,
                target_space=target_space,
                attachments_count=len(note.attachments),
            )

            # Check if already imported (database check - fast)
            if skip_existing_db and db.is_note_imported(note_id, wiki_url):
                db.update_record_status(record_id, ImportStatus.SKIPPED, error_message="Already imported (database)")
                skipped += 1
                with log_container:
                    st.text(f"  Skipped (in database): {note.title}")
                continue

            # Convert and upload
            try:
                page = convert_note(note, target_space)

                # Check if page exists in XWiki (slower - requires API call)
                if skip_existing_xwiki and xwiki_client.page_exists(page.space, page.page_name):
                    db.update_record_status(record_id, ImportStatus.SKIPPED, error_message="Already exists in XWiki")
                    skipped += 1
                    with log_container:
                        st.text(f"  Skipped (exists in XWiki): {note.title}")
                    continue

                result = xwiki_client.create_or_update_page(page)

                if result.success:
                    db.update_record_status(
                        record_id,
                        ImportStatus.COMPLETED,
                        page_url=result.page_url,
                        attachments_uploaded=result.attachments_uploaded,
                    )
                    completed += 1
                    with log_container:
                        st.text(f"  Imported: {note.title}")
                else:
                    db.update_record_status(
                        record_id,
                        ImportStatus.FAILED,
                        error_message=result.error,
                    )
                    failed += 1
                    with log_container:
                        st.text(f"  Failed: {note.title} - {result.error}")

            except Exception as e:
                db.update_record_status(
                    record_id,
                    ImportStatus.FAILED,
                    error_message=str(e),
                )
                failed += 1
                with log_container:
                    st.text(f"  Error: {note.title} - {e}")

            # Update session counts
            db.update_session_counts(session_id, completed, failed, skipped)

            # Update status
            status_container.markdown(
                f"**Progress:** {completed} completed | {failed} failed | {skipped} skipped"
            )

    # Finish session
    final_status = ImportStatus.COMPLETED if failed == 0 else ImportStatus.FAILED
    db.finish_session(session_id, final_status)

    # Final summary
    progress_bar.progress(1.0, text="Import complete!")

    if failed == 0:
        st.success(f"Import completed! {completed} notes imported, {skipped} skipped.")
    else:
        st.warning(f"Import completed with errors. {completed} imported, {failed} failed, {skipped} skipped.")


def render_import_page(db: ImportDatabase):
    """Render the ENEX file import page."""
    st.header("Import from ENEX Files")

    # Load saved configuration
    config = load_config()

    # Configuration section
    with st.expander("XWiki Configuration", expanded=True):
        col1, col2 = st.columns(2)

        with col1:
            wiki_url = st.text_input(
                "XWiki URL",
                value=config.get("wiki_url", ""),
                placeholder="https://yourwiki.xwiki.cloud",
                help="The base URL of your XWiki instance",
            )

        with col2:
            target_space = st.text_input(
                "Target Space",
                value=config.get("target_space", "ImportedNotes"),
                help="XWiki space where notes will be imported",
            )

        # Username and password for HTTP Basic Auth
        col3, col4 = st.columns(2)

        with col3:
            # Check environment variable first
            env_username = os.environ.get("XWIKI_USERNAME", "")
            if env_username:
                st.info(f"Using username from XWIKI_USERNAME: {env_username}")
                username = env_username
            else:
                username = st.text_input(
                    "Username",
                    value=config.get("username", ""),
                    placeholder="Admin",
                    help="Your XWiki username. Can also be set via XWIKI_USERNAME environment variable.",
                )

        with col4:
            env_password = os.environ.get("XWIKI_PASSWORD", "")
            if env_password:
                st.info("Using password from XWIKI_PASSWORD")
                password = env_password
            else:
                password = st.text_input(
                    "Password",
                    value=config.get("password", ""),
                    type="password",
                    help="Your XWiki password. Can also be set via XWIKI_PASSWORD environment variable.",
                )

        # Test Connection buttons
        btn_col1, btn_col2, btn_col3 = st.columns(3)

        with btn_col1:
            if st.button("Test Connection", type="secondary"):
                if not wiki_url:
                    st.error("Please enter a Wiki URL")
                elif not username:
                    st.error("Please enter a username")
                elif not password:
                    st.error("Please enter a password")
                else:
                    with st.spinner("Testing connection..."):
                        try:
                            client = XWikiClient(
                                wiki_url=wiki_url,
                                username=username,
                                password=password,
                            )
                            result = client.test_connection_detailed()

                            if result["success"]:
                                st.success(f"Connection successful!")
                                st.caption(f"Tested URL: `{result['url_tested']}`")
                            else:
                                st.error(f"Connection failed: {result['error']}")
                                st.caption(f"Tested URL: `{result['url_tested']}`")
                                st.info(
                                    "**URL Tips:**\n"
                                    "- For XWiki Cloud, try: `https://yourinstance.xwiki.cloud/xwiki`\n"
                                    "- Or without /xwiki: `https://yourinstance.xwiki.cloud`\n"
                                    "- Check what URL you see in your browser when logged into XWiki"
                                )
                        except Exception as e:
                            st.error(f"Connection error: {e}")

        with btn_col2:
            if st.button("Test Page Creation", type="secondary"):
                if not wiki_url or not username or not password:
                    st.error("Please fill in all XWiki credentials first")
                else:
                    with st.spinner("Testing page creation..."):
                        try:
                            client = XWikiClient(
                                wiki_url=wiki_url,
                                username=username,
                                password=password,
                            )
                            result = client.test_page_creation(target_space, "EvernoteImporterTest")

                            if result.get("success"):
                                st.success("Page creation test successful!")
                                st.caption(f"Created test page at: `{result.get('url')}`")
                                st.info("You can delete the test page 'EvernoteImporterTest' from XWiki.")
                            else:
                                st.error(f"Page creation failed!")
                                st.code(f"""
Status: {result.get('status_code')}
URL: {result.get('url')}
Form Token: {result.get('form_token_present')}
Response: {result.get('response', result.get('error'))}
""")
                        except Exception as e:
                            st.error(f"Error: {e}")

        with btn_col3:
            if st.button("Debug Auth", type="secondary"):
                if not wiki_url or not username or not password:
                    st.error("Please fill in all XWiki credentials first")
                else:
                    with st.spinner("Checking authentication..."):
                        try:
                            client = XWikiClient(
                                wiki_url=wiki_url,
                                username=username,
                                password=password,
                            )
                            result = client.check_user_info()
                            st.code(f"""
REST Root: {result.get('rest_root')}
Wiki Info: {result.get('wiki_info')}
Read Test: {result.get('read_test')}

Username sent: {username}
Auth header present: True
""")
                        except Exception as e:
                            st.error(f"Error: {e}")

    # File selection
    st.subheader("Select Source")

    source_type = st.radio(
        "Source Type",
        ["Single File", "Directory"],
        horizontal=True,
    )

    source_path = st.text_input(
        "Path to ENEX file(s)",
        value=config.get("source_path", ""),
        placeholder="/path/to/notes.enex or /path/to/exports/",
        help="Enter the full path to an ENEX file or directory containing ENEX files",
    )

    # Options
    col1, col2 = st.columns(2)
    with col1:
        dry_run = st.checkbox("Dry Run", help="Preview without uploading")
    with col2:
        rate_limit = st.slider("Rate Limit (seconds)", 0.1, 2.0, 0.5, 0.1)

    # Skip options
    st.markdown("**Skip Options**")
    col1, col2 = st.columns(2)
    with col1:
        skip_existing_db = st.checkbox(
            "Skip if previously imported (database)",
            value=True,
            help="Skip notes that were imported in a previous session (fast, checks local database)",
        )
    with col2:
        skip_existing_xwiki = st.checkbox(
            "Skip if exists in XWiki",
            value=False,
            help="Skip notes that already exist in XWiki (slower, checks XWiki API for each note)",
        )

    # Validation
    can_import = True
    validation_messages = []

    if not source_path:
        can_import = False
        validation_messages.append("Please enter a source path")
    elif not Path(source_path).exists():
        can_import = False
        validation_messages.append(f"Path does not exist: {source_path}")
    elif source_type == "Single File" and not source_path.endswith(".enex"):
        can_import = False
        validation_messages.append("Single file must be an .enex file")

    if not wiki_url and not dry_run:
        can_import = False
        validation_messages.append("XWiki URL is required (unless doing a dry run)")

    if not username and not dry_run:
        can_import = False
        validation_messages.append("Username is required (unless doing a dry run)")

    if not password and not dry_run:
        can_import = False
        validation_messages.append("Password is required (unless doing a dry run)")

    # Show validation messages
    if validation_messages:
        for msg in validation_messages:
            st.warning(msg)

    # Action buttons
    btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 2])

    with btn_col1:
        if st.button("Save Settings"):
            new_config = {
                "wiki_url": wiki_url,
                "target_space": target_space,
                "username": username,
                "password": password,
                "source_path": source_path,
            }
            save_config(new_config)
            st.success("Settings saved!")

    with btn_col2:
        if st.button("Start Import", disabled=not can_import, type="primary"):
            # Save settings before import
            new_config = {
                "wiki_url": wiki_url,
                "target_space": target_space,
                "username": username,
                "password": password,
                "source_path": source_path,
            }
            save_config(new_config)

            run_import(
                db=db,
                source_path=source_path,
                wiki_url=wiki_url,
                username=username,
                password=password,
                target_space=target_space,
                dry_run=dry_run,
                skip_existing_db=skip_existing_db,
                skip_existing_xwiki=skip_existing_xwiki,
                rate_limit=rate_limit,
            )


def run_import(
    db: ImportDatabase,
    source_path: str,
    wiki_url: str,
    username: str,
    password: str,
    target_space: str,
    dry_run: bool,
    skip_existing_db: bool,
    skip_existing_xwiki: bool,
    rate_limit: float,
):
    """Run the import process."""
    source = Path(source_path)

    # Count notes first (recursively for directories)
    with st.spinner("Scanning ENEX files..."):
        total_notes = 0
        enex_files = []
        if source.is_file():
            total_notes = count_notes_in_enex(source)
            enex_files = [source]
        else:
            # Recursively find all ENEX files
            enex_files = list(source.rglob("*.enex"))
            for enex_file in enex_files:
                total_notes += count_notes_in_enex(enex_file)

        if len(enex_files) > 1:
            st.info(f"Found {len(enex_files)} ENEX files in directory tree")

    if total_notes == 0:
        st.error("No notes found in the specified path.")
        return

    st.info(f"Found {total_notes} notes to process")

    # Create session in database
    session_id = db.create_session(
        source_path=str(source),
        wiki_url=wiki_url or "dry-run",
        target_space=target_space,
        total_notes=total_notes,
    )

    # Initialize XWiki client
    client = None
    if not dry_run:
        client = XWikiClient(
            wiki_url=wiki_url,
            username=username,
            password=password,
            rate_limit_delay=rate_limit,
        )

        # Test connection
        with st.spinner("Connecting to XWiki..."):
            if not client.test_connection():
                st.error("Could not connect to XWiki. Please check your URL and credentials.")
                db.finish_session(session_id, ImportStatus.FAILED)
                return

        st.success("Connected to XWiki successfully!")

    # Progress tracking
    progress_bar = st.progress(0, text="Starting import...")
    status_container = st.empty()
    log_container = st.container()

    completed = 0
    failed = 0
    skipped = 0

    # Get notes iterator
    if source.is_file():
        notes_iter = ((source, note) for note in parse_enex_file(source))
    else:
        notes_iter = parse_enex_directory(source)

    # Process notes
    for i, (file_path, note) in enumerate(notes_iter):
        note_id = generate_note_identifier(note.title, note.created)

        # Create record in database
        record_id = db.create_record(
            session_id=session_id,
            source_file=str(file_path),
            note_title=note.title,
            note_identifier=note_id,
            wiki_url=wiki_url or "dry-run",
            target_space=target_space,
            attachments_count=len(note.attachments),
        )

        # Check if already imported (database check - fast)
        if skip_existing_db and not dry_run and db.is_note_imported(note_id, wiki_url):
            db.update_record_status(record_id, ImportStatus.SKIPPED, error_message="Already imported (database)")
            skipped += 1
            with log_container:
                st.text(f"⏭️ Skipped (in database): {note.title}")
            continue

        # Convert note
        try:
            page = convert_note(note, target_space)

            # Check if page exists in XWiki (slower - requires API call)
            if skip_existing_xwiki and not dry_run and client.page_exists(page.space, page.page_name):
                db.update_record_status(record_id, ImportStatus.SKIPPED, error_message="Already exists in XWiki")
                skipped += 1
                with log_container:
                    st.text(f"⏭️ Skipped (exists in XWiki): {note.title}")
                continue

            if dry_run:
                db.update_record_status(
                    record_id,
                    ImportStatus.COMPLETED,
                    page_url=f"[dry-run] {page.space}/{page.page_name}",
                )
                completed += 1
                with log_container:
                    st.text(f"✅ [DRY RUN] Would import: {note.title}")
            else:
                # Upload to XWiki
                result = client.create_or_update_page(page)

                if result.success:
                    db.update_record_status(
                        record_id,
                        ImportStatus.COMPLETED,
                        page_url=result.page_url,
                        attachments_uploaded=result.attachments_uploaded,
                    )
                    completed += 1
                    with log_container:
                        st.text(f"✅ Imported: {note.title}")
                else:
                    db.update_record_status(
                        record_id,
                        ImportStatus.FAILED,
                        error_message=result.error,
                    )
                    failed += 1
                    with log_container:
                        st.text(f"❌ Failed: {note.title} - {result.error}")

        except Exception as e:
            db.update_record_status(
                record_id,
                ImportStatus.FAILED,
                error_message=str(e),
            )
            failed += 1
            with log_container:
                st.text(f"❌ Error: {note.title} - {e}")

        # Update progress
        progress = (i + 1) / total_notes
        progress_bar.progress(progress, text=f"Processing {i + 1}/{total_notes}: {note.title[:50]}...")

        # Update session counts
        db.update_session_counts(session_id, completed, failed, skipped)

        # Update status display
        status_container.markdown(
            f"**Progress:** {completed} completed | {failed} failed | {skipped} skipped"
        )

    # Finish session
    final_status = ImportStatus.COMPLETED if failed == 0 else ImportStatus.FAILED
    db.finish_session(session_id, final_status)

    # Final summary
    progress_bar.progress(1.0, text="Import complete!")

    if failed == 0:
        st.success(f"Import completed successfully! {completed} notes imported, {skipped} skipped.")
    else:
        st.warning(f"Import completed with errors. {completed} imported, {failed} failed, {skipped} skipped.")

    if dry_run:
        st.info("This was a dry run - no changes were made to XWiki.")


def render_history_page(db: ImportDatabase):
    """Render the import history page."""
    st.header("Import History")

    # Session filter
    sessions = db.get_recent_sessions(limit=50)

    if not sessions:
        st.info("No import sessions found. Start an import to see history here.")
        return

    # Session selector
    session_options = {
        f"Session {s.id} - {s.started_at.strftime('%Y-%m-%d %H:%M')} ({s.status.value})": s.id
        for s in sessions
    }

    selected = st.selectbox("Select Session", options=list(session_options.keys()))
    session_id = session_options[selected]

    session = db.get_session(session_id)

    if session:
        # Session details
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Notes", session.total_notes)
        with col2:
            st.metric("Completed", session.completed_notes)
        with col3:
            st.metric("Failed", session.failed_notes)
        with col4:
            st.metric("Skipped", session.skipped_notes)

        st.markdown(f"**Source:** `{session.source_path}`")
        st.markdown(f"**Wiki URL:** {session.wiki_url}")
        st.markdown(f"**Target Space:** {session.target_space}")

        # Record filters
        st.subheader("Import Records")

        status_filter = st.selectbox(
            "Filter by Status",
            ["All", "Completed", "Failed", "Skipped", "Pending"],
        )

        status_map = {
            "All": None,
            "Completed": ImportStatus.COMPLETED,
            "Failed": ImportStatus.FAILED,
            "Skipped": ImportStatus.SKIPPED,
            "Pending": ImportStatus.PENDING,
        }

        records = db.get_session_records(
            session_id,
            status=status_map[status_filter],
            limit=100,
        )

        if records:
            # Display as table
            table_data = []
            for r in records:
                table_data.append({
                    "Title": r.note_title[:50] + "..." if len(r.note_title) > 50 else r.note_title,
                    "Status": r.status.value,
                    "Page URL": r.page_url or "-",
                    "Attachments": f"{r.attachments_uploaded}/{r.attachments_count}",
                    "Error": r.error_message[:30] + "..." if r.error_message and len(r.error_message) > 30 else (r.error_message or "-"),
                    "Updated": r.updated_at.strftime("%H:%M:%S"),
                })

            st.dataframe(table_data, use_container_width=True)
        else:
            st.info("No records found for the selected filter.")

        # Delete session button
        if st.button("Delete Session", type="secondary"):
            db.delete_session(session_id)
            st.success("Session deleted. Refresh to see changes.")
            st.rerun()


def render_stats_page(db: ImportDatabase):
    """Render the statistics page."""
    st.header("Import Statistics")

    stats = db.get_stats()

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Notes Processed", stats["total_notes"])

    with col2:
        st.metric("Successfully Imported", stats["completed"])

    with col3:
        st.metric("Failed", stats["failed"])

    with col4:
        st.metric("Total Sessions", stats["total_sessions"])

    # Success rate
    if stats["total_notes"] > 0:
        success_rate = (stats["completed"] / stats["total_notes"]) * 100
        st.progress(success_rate / 100, text=f"Success Rate: {success_rate:.1f}%")

    # Recent sessions
    st.subheader("Recent Sessions")

    sessions = db.get_recent_sessions(limit=10)

    if sessions:
        table_data = []
        for s in sessions:
            duration = ""
            if s.finished_at:
                delta = s.finished_at - s.started_at
                duration = f"{delta.seconds // 60}m {delta.seconds % 60}s"

            table_data.append({
                "ID": s.id,
                "Started": s.started_at.strftime("%Y-%m-%d %H:%M"),
                "Status": s.status.value,
                "Total": s.total_notes,
                "Completed": s.completed_notes,
                "Failed": s.failed_notes,
                "Duration": duration or "In progress",
            })

        st.dataframe(table_data, use_container_width=True)
    else:
        st.info("No sessions found.")

    # Failed notes summary
    st.subheader("Recent Failed Imports")

    failed_records = db.get_all_records(status=ImportStatus.FAILED, limit=20)

    if failed_records:
        for r in failed_records:
            with st.expander(f"❌ {r.note_title}"):
                st.markdown(f"**Source:** `{r.source_file}`")
                st.markdown(f"**Error:** {r.error_message}")
                st.markdown(f"**Time:** {r.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        st.success("No failed imports!")


if __name__ == "__main__":
    main()

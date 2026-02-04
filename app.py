"""Streamlit UI for Evernote to XWiki extraction tool."""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st
from streamlit_file_browser import st_file_browser

# Handle imports - add parent to path for package imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from Evernote_Extractor.converter import convert_note
from Evernote_Extractor.database import ImportDatabase, ImportStatus
from Evernote_Extractor.enex_parser import build_enex_inventory, count_notes_in_enex, parse_enex_directory, parse_enex_file
from Evernote_Extractor.progress import generate_note_identifier
from Evernote_Extractor.xwiki_client import XWikiClient
from Evernote_Extractor.evernote_api import (
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
    initial_sidebar_state="expanded",
)

# Custom CSS for professional styling
st.markdown("""
<style>
    /* Import Google Font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    /* Global styles */
    .stApp {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    /* Hide default Streamlit header and footer */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* Main content area */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 1200px;
    }

    /* Custom header styling */
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem 2.5rem;
        border-radius: 16px;
        margin-bottom: 2rem;
        box-shadow: 0 10px 40px rgba(102, 126, 234, 0.3);
    }

    .main-header h1 {
        color: white !important;
        font-size: 2.2rem !important;
        font-weight: 700 !important;
        margin: 0 !important;
        padding: 0 !important;
    }

    .main-header p {
        color: rgba(255, 255, 255, 0.9) !important;
        font-size: 1.1rem !important;
        margin-top: 0.5rem !important;
        margin-bottom: 0 !important;
    }

    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1f36 0%, #252d4a 100%);
        padding-top: 1rem;
    }

    [data-testid="stSidebar"] .stRadio > label {
        color: rgba(255, 255, 255, 0.6) !important;
        font-size: 0.75rem !important;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        font-weight: 600;
    }

    [data-testid="stSidebar"] .stRadio > div {
        gap: 0.25rem;
    }

    [data-testid="stSidebar"] .stRadio > div > label {
        background: rgba(255, 255, 255, 0.05);
        border-radius: 8px;
        padding: 0.75rem 1rem !important;
        margin: 0.25rem 0;
        transition: all 0.2s ease;
        border: 1px solid transparent;
    }

    [data-testid="stSidebar"] .stRadio > div > label:hover {
        background: rgba(255, 255, 255, 0.1);
        border-color: rgba(102, 126, 234, 0.5);
    }

    [data-testid="stSidebar"] .stRadio > div > label[data-checked="true"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-color: transparent;
    }

    [data-testid="stSidebar"] .stRadio > div > label span,
    [data-testid="stSidebar"] .stRadio > div > label p,
    [data-testid="stSidebar"] .stRadio > div > label div,
    [data-testid="stSidebar"] .stRadio label,
    [data-testid="stSidebar"] .stRadio p,
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
        color: white !important;
        font-weight: 500;
    }

    /* Ensure all sidebar text is visible */
    [data-testid="stSidebar"] * {
        color: white;
    }

    [data-testid="stSidebar"] .stRadio > div {
        color: white !important;
    }

    /* Sidebar logo area */
    .sidebar-logo {
        padding: 1.5rem;
        text-align: center;
        border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        margin-bottom: 1rem;
    }

    .sidebar-logo h2 {
        color: white !important;
        font-size: 1.3rem !important;
        font-weight: 700 !important;
        margin: 0 !important;
    }

    .sidebar-logo p {
        color: rgba(255, 255, 255, 0.5) !important;
        font-size: 0.8rem !important;
        margin-top: 0.25rem !important;
    }

    /* Card styling */
    .config-card {
        background: white;
        border-radius: 12px;
        padding: 1.5rem;
        box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
        border: 1px solid #e5e7eb;
        margin-bottom: 1.5rem;
    }

    .config-card-header {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin-bottom: 1rem;
        padding-bottom: 0.75rem;
        border-bottom: 1px solid #f3f4f6;
    }

    .config-card-header h3 {
        color: #1f2937 !important;
        font-size: 1.1rem !important;
        font-weight: 600 !important;
        margin: 0 !important;
    }

    .config-card-icon {
        width: 36px;
        height: 36px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.1rem;
    }

    /* Section headers */
    .section-header {
        color: #1f2937;
        font-size: 1.5rem;
        font-weight: 700;
        margin: 1.5rem 0 1rem 0;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    .section-subheader {
        color: #6b7280;
        font-size: 0.95rem;
        margin-bottom: 1.5rem;
    }

    /* Metric cards */
    .metric-card {
        background: white;
        border-radius: 12px;
        padding: 1.25rem;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
        border: 1px solid #e5e7eb;
        text-align: center;
    }

    .metric-value {
        font-size: 2rem;
        font-weight: 700;
        color: #1f2937;
        line-height: 1.2;
    }

    .metric-label {
        font-size: 0.85rem;
        color: #6b7280;
        margin-top: 0.25rem;
        font-weight: 500;
    }

    .metric-success { color: #059669 !important; }
    .metric-danger { color: #dc2626 !important; }
    .metric-warning { color: #d97706 !important; }
    .metric-info { color: #667eea !important; }

    /* Input styling */
    .stTextInput > div > div > input {
        border-radius: 8px;
        border: 1.5px solid #e5e7eb;
        padding: 0.625rem 0.875rem;
        font-size: 0.95rem;
        transition: all 0.2s ease;
    }

    .stTextInput > div > div > input:focus {
        border-color: #667eea;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.15);
    }

    /* Button styling */
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
        padding: 0.5rem 1.25rem;
        transition: all 0.2s ease;
        border: none;
    }

    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        box-shadow: 0 4px 14px rgba(102, 126, 234, 0.4);
    }

    .stButton > button[kind="primary"]:hover {
        box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5);
        transform: translateY(-1px);
    }

    .stButton > button[kind="secondary"] {
        background: white;
        color: #374151;
        border: 1.5px solid #e5e7eb;
    }

    .stButton > button[kind="secondary"]:hover {
        background: #f9fafb;
        border-color: #d1d5db;
    }

    /* Expander styling */
    .streamlit-expanderHeader {
        background: #f9fafb;
        border-radius: 8px;
        font-weight: 600;
        color: #374151;
    }

    .streamlit-expanderContent {
        border: 1px solid #e5e7eb;
        border-top: none;
        border-radius: 0 0 8px 8px;
        padding: 1rem;
    }

    /* Progress bar */
    .stProgress > div > div {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 10px;
    }

    .stProgress {
        height: 8px;
    }

    /* Alerts */
    .stAlert {
        border-radius: 10px;
        border: none;
    }

    /* Dataframe styling */
    .stDataFrame {
        border-radius: 10px;
        overflow: hidden;
    }

    /* Status badges */
    .status-badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.025em;
    }

    .status-success {
        background: #d1fae5;
        color: #065f46;
    }

    .status-error {
        background: #fee2e2;
        color: #991b1b;
    }

    .status-warning {
        background: #fef3c7;
        color: #92400e;
    }

    .status-info {
        background: #e0e7ff;
        color: #3730a3;
    }

    /* Footer */
    .app-footer {
        text-align: center;
        padding: 2rem 0 1rem 0;
        margin-top: 3rem;
        border-top: 1px solid #e5e7eb;
        color: #9ca3af;
        font-size: 0.85rem;
    }

    .app-footer a {
        color: #667eea;
        text-decoration: none;
    }

    /* Connection status indicator */
    .connection-status {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.75rem 1rem;
        border-radius: 8px;
        font-weight: 500;
    }

    .connection-connected {
        background: #d1fae5;
        color: #065f46;
    }

    .connection-disconnected {
        background: #fee2e2;
        color: #991b1b;
    }

    /* Info box styling */
    .info-box {
        background: #f0f4ff;
        border-left: 4px solid #667eea;
        padding: 1rem;
        border-radius: 0 8px 8px 0;
        margin: 1rem 0;
    }

    .info-box p {
        margin: 0;
        color: #4338ca;
    }

    /* Checkbox styling */
    .stCheckbox > label > span {
        font-weight: 500;
        color: #374151;
    }

    /* Slider styling */
    .stSlider > div > div > div {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    }

    /* Tab styling when used */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        background: #f3f4f6;
        border-radius: 10px;
        padding: 4px;
    }

    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        font-weight: 600;
        padding: 0.5rem 1.5rem;
    }

    .stTabs [aria-selected="true"] {
        background: white;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    }

    /* Quick stats row */
    .quick-stats {
        display: flex;
        gap: 1rem;
        margin-bottom: 1.5rem;
    }

    .quick-stat {
        flex: 1;
        background: white;
        border-radius: 10px;
        padding: 1rem;
        text-align: center;
        border: 1px solid #e5e7eb;
    }

    /* Log entries */
    .log-entry {
        padding: 0.5rem 0.75rem;
        border-radius: 6px;
        margin: 0.25rem 0;
        font-family: 'SF Mono', Monaco, monospace;
        font-size: 0.85rem;
    }

    .log-success {
        background: #f0fdf4;
        color: #166534;
    }

    .log-error {
        background: #fef2f2;
        color: #991b1b;
    }

    .log-skip {
        background: #fefce8;
        color: #854d0e;
    }
</style>
""", unsafe_allow_html=True)

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


def render_sidebar_header():
    """Render the sidebar header with logo and branding."""
    st.sidebar.markdown("""
    <div class="sidebar-logo">
        <h2>📝 Evernote → XWiki</h2>
        <p>Migration Tool</p>
    </div>
    """, unsafe_allow_html=True)


def render_main_header(title: str, subtitle: str = ""):
    """Render the main page header."""
    subtitle_html = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(f"""
    <div class="main-header">
        <h1>{title}</h1>
        {subtitle_html}
    </div>
    """, unsafe_allow_html=True)


def render_section_header(title: str, icon: str = "", subtitle: str = ""):
    """Render a section header with optional icon and subtitle."""
    icon_html = f"{icon} " if icon else ""
    st.markdown(f'<div class="section-header">{icon_html}{title}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="section-subheader">{subtitle}</div>', unsafe_allow_html=True)


def render_metric_card(label: str, value: str | int, color_class: str = ""):
    """Render a styled metric card."""
    color = f" {color_class}" if color_class else ""
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value{color}">{value}</div>
        <div class="metric-label">{label}</div>
    </div>
    """, unsafe_allow_html=True)


def render_footer():
    """Render the application footer."""
    st.markdown("""
    <div class="app-footer">
        <p>Evernote to XWiki Importer &bull; Built with Streamlit</p>
    </div>
    """, unsafe_allow_html=True)


def render_path_chooser(label: str, default_value: str, key_prefix: str, help_text: str) -> str:
    """Render a path input with an interactive file browser.

    Provides both a text input for typing/pasting and an expandable file browser
    for visually selecting ENEX files or directories. The browser includes a
    "Browse from" input so the user can navigate to any location on the filesystem.

    Returns the selected path string.
    """
    # Determine the session state key for the chosen path
    state_key = f"{key_prefix}_chosen_path"

    # If the browser previously set a path, use it as the default
    if state_key in st.session_state:
        default_value = st.session_state[state_key]

    source_path = st.text_input(
        label,
        value=default_value,
        placeholder="/path/to/notes.enex or /path/to/exports/",
        help=help_text,
        key=f"{key_prefix}_text_input",
    )

    with st.expander("Browse for file or directory..."):
        # Let the user set where the browser starts
        browse_root_key = f"{key_prefix}_browse_root"
        default_root = str(Path.home())
        if source_path and Path(source_path).exists():
            default_root = str(Path(source_path).parent) if Path(source_path).is_file() else source_path

        browse_root = st.text_input(
            "Browse from",
            value=st.session_state.get(browse_root_key, default_root),
            key=browse_root_key,
            help="Change this to browse a different location",
        )

        # Validate browse root
        if not browse_root or not Path(browse_root).is_dir():
            st.warning("Enter a valid directory path above to browse.")
        else:
            event = st_file_browser(
                browse_root,
                key=f"{key_prefix}_browser",
                show_choose_file=True,
                show_choose_folder=True,
                show_preview=False,
                show_download_file=False,
            )

            if event and event.get("type") in ("CHOOSE_FILE", "CHOOSE_FOLDER"):
                target = event.get("target", {})
                relative_path = target.get("path", "")
                if relative_path:
                    chosen = str(Path(browse_root) / relative_path)
                else:
                    chosen = browse_root
                st.session_state[state_key] = chosen
                source_path = chosen
                st.rerun()

    return source_path


def main():
    """Main application."""
    db = get_database()

    # Sidebar
    render_sidebar_header()

    # Navigation with icons
    page = st.sidebar.radio(
        "NAVIGATION",
        ["🔗  Import from Evernote", "📄  Import from ENEX Files", "📋  Import History", "🔍  Reconciliation", "📊  Statistics"],
        index=0,
        label_visibility="visible",
    )

    # Sidebar footer
    st.sidebar.markdown("---")
    st.sidebar.markdown("""
    <div style="padding: 1rem; color: rgba(255,255,255,0.5); font-size: 0.8rem;">
        <p style="margin: 0;">Need help?</p>
        <p style="margin: 0.5rem 0 0 0; color: rgba(255,255,255,0.7);">
            Check the documentation or visit the GitHub repository.
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Route to pages
    if "Evernote" in page and "ENEX" not in page:
        render_evernote_direct_page(db)
    elif "ENEX" in page:
        render_import_page(db)
    elif "History" in page:
        render_history_page(db)
    elif "Reconciliation" in page:
        render_reconciliation_page(db)
    else:
        render_stats_page(db)

    # Footer
    render_footer()


def render_evernote_direct_page(db: ImportDatabase):
    """Render the direct Evernote import page."""
    render_main_header(
        "Import from Evernote",
        "Connect directly to your Evernote account and import notes to XWiki"
    )

    # Load config
    config = load_config()

    # Evernote API Configuration
    with st.expander("🔑  Evernote API Configuration", expanded=not config.get("evernote_consumer_key")):
        st.markdown("""
        <div class="info-box">
            <p><strong>To get credentials:</strong> Visit the <a href="https://dev.evernote.com/" target="_blank">Evernote Developer Portal</a>,
            create a new API Key, and enter your Consumer Key and Secret below.</p>
        </div>
        """, unsafe_allow_html=True)

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

        st.markdown("<br>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            if st.button("💾  Save API Settings", type="secondary", use_container_width=True):
                config["evernote_consumer_key"] = consumer_key
                config["evernote_consumer_secret"] = consumer_secret
                config["evernote_sandbox"] = use_sandbox
                save_config(config)
                st.success("✓ Evernote API settings saved!")

    # Check if API credentials are configured
    if not config.get("evernote_consumer_key") or not config.get("evernote_consumer_secret"):
        st.warning("Please configure your Evernote API credentials above to continue.")
        return

    # XWiki Configuration
    with st.expander("🌐  XWiki Configuration", expanded=True):
        col1, col2 = st.columns(2)

        with col1:
            wiki_url = st.text_input(
                "XWiki URL",
                value=config.get("wiki_url", ""),
                placeholder="https://yourwiki.xwiki.cloud",
                help="The base URL of your XWiki instance"
            )

        with col2:
            target_space = st.text_input(
                "Target Space",
                value=config.get("target_space", "ImportedNotes"),
                help="XWiki space where notes will be imported"
            )

        col3, col4 = st.columns(2)

        with col3:
            username = st.text_input(
                "XWiki Username",
                value=config.get("username", ""),
                help="Your XWiki login username"
            )

        with col4:
            password = st.text_input(
                "XWiki Password",
                value=config.get("password", ""),
                type="password",
                help="Your XWiki login password"
            )

    # Evernote Connection
    st.markdown("---")
    render_section_header("Connect to Evernote", "🔗", "Authenticate with your Evernote account")

    # Check for existing token
    existing_token = load_token()

    if existing_token:
        st.markdown("""
        <div class="connection-status connection-connected">
            <span>✓</span> <strong>Connected to Evernote</strong> — Authentication token saved
        </div>
        """, unsafe_allow_html=True)

        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            if st.button("🔌  Disconnect", type="secondary"):
                delete_token()
                st.rerun()

        with col2:
            if st.button("🔄  Test Connection", type="secondary"):
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
                            st.success(f"✓ Connected as: **{user_info.get('username', 'Unknown')}**")
                    except Exception as e:
                        st.error(f"Connection failed: {e}")

        # Notebook selection and import
        st.markdown("---")
        render_section_header("Select Notebooks", "📚", "Choose which notebooks to import to XWiki")

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
                st.markdown("---")
                render_section_header("Import Options", "⚙️", "Configure how notes should be imported")

                col1, col2 = st.columns([1, 1])
                with col1:
                    rate_limit = st.slider(
                        "API Rate Limit (seconds between requests)",
                        0.1, 2.0, 0.5, 0.1,
                        help="Delay between API calls to avoid rate limiting"
                    )

                with col2:
                    st.markdown("**Skip Existing Notes**")
                    skip_existing_db = st.checkbox(
                        "Skip if in local database",
                        value=True,
                        help="Skip notes that were imported in a previous session (fast)",
                        key="evernote_skip_db",
                    )
                    skip_existing_xwiki = st.checkbox(
                        "Skip if exists in XWiki",
                        value=False,
                        help="Check XWiki for each note before importing (slower)",
                        key="evernote_skip_xwiki",
                    )

                # Import button
                st.markdown("<br>", unsafe_allow_html=True)
                btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 2])
                with btn_col1:
                    start_import = st.button(
                        "🚀  Start Import",
                        disabled=not selected_notebooks or not wiki_url or not username or not password,
                        type="primary",
                        use_container_width=True,
                    )

                if start_import:
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
        st.markdown("""
        <div class="connection-status connection-disconnected">
            <span>○</span> <strong>Not Connected</strong> — Click below to authenticate with Evernote
        </div>
        """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            connect_btn = st.button("🔗  Connect to Evernote", type="primary", use_container_width=True)

        if connect_btn:
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
            from Evernote_Extractor.progress import generate_note_identifier

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
    render_main_header(
        "Import from ENEX Files",
        "Import notes from Evernote export files (.enex) to XWiki"
    )

    # Load saved configuration
    config = load_config()

    # Configuration section
    with st.expander("🌐  XWiki Configuration", expanded=True):
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
        st.markdown("<br>", unsafe_allow_html=True)
        btn_col1, btn_col2, btn_col3 = st.columns(3)

        with btn_col1:
            if st.button("🔌  Test Connection", type="secondary", use_container_width=True):
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
            if st.button("📝  Test Page Creation", type="secondary", use_container_width=True):
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
            if st.button("🔍  Debug Auth", type="secondary", use_container_width=True):
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
    st.markdown("---")
    render_section_header("Select Source", "📁", "Choose the ENEX file or folder to import")

    source_type = st.radio(
        "Source Type",
        ["📄  Single File", "📂  Directory"],
        horizontal=True,
        label_visibility="collapsed"
    )

    source_path = render_path_chooser(
        label="Path to ENEX file(s)",
        default_value=config.get("source_path", ""),
        key_prefix="import_source",
        help_text="Enter the full path to an ENEX file or directory containing ENEX files",
    )

    # Options
    st.markdown("---")
    render_section_header("Import Options", "⚙️", "Configure how notes should be imported")

    col1, col2 = st.columns(2)
    with col1:
        dry_run = st.checkbox(
            "🔍  Dry Run Mode",
            help="Preview the import without making any changes to XWiki"
        )
        rate_limit = st.slider(
            "API Rate Limit (seconds)",
            0.1, 2.0, 0.5, 0.1,
            help="Delay between API calls to avoid rate limiting"
        )

    with col2:
        st.markdown("**Skip Existing Notes**")
        skip_existing_db = st.checkbox(
            "Skip if in local database",
            value=True,
            help="Skip notes that were imported in a previous session (fast)",
        )
        skip_existing_xwiki = st.checkbox(
            "Skip if exists in XWiki",
            value=False,
            help="Check XWiki for each note before importing (slower)",
        )

    # Validation
    can_import = True
    validation_messages = []

    # Adjust source_type check for new format with emoji
    is_single_file = "Single" in source_type

    if not source_path:
        can_import = False
        validation_messages.append("Please enter a source path")
    elif not Path(source_path).exists():
        can_import = False
        validation_messages.append(f"Path does not exist: {source_path}")
    elif is_single_file and not source_path.endswith(".enex"):
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
        st.markdown("---")
        for msg in validation_messages:
            st.warning(msg)

    # Action buttons
    st.markdown("---")
    btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 2])

    with btn_col1:
        if st.button("💾  Save Settings", type="secondary", use_container_width=True):
            new_config = {
                "wiki_url": wiki_url,
                "target_space": target_space,
                "username": username,
                "password": password,
                "source_path": source_path,
            }
            save_config(new_config)
            st.success("✓ Settings saved!")

    with btn_col2:
        scan_clicked = st.button(
            "🔍  Scan & Preview",
            disabled=not can_import,
            type="primary",
            use_container_width=True,
        )

    # Phase 1: Scan and show manifest
    if scan_clicked and can_import:
        with st.spinner("Scanning ENEX files..."):
            try:
                inventory, grand_total = build_enex_inventory(source_path)
                st.session_state["import_manifest"] = inventory
                st.session_state["import_manifest_total"] = grand_total
                st.session_state["import_manifest_source"] = source_path
            except Exception as e:
                st.error(f"Error scanning ENEX files: {e}")

    # Phase 2: Display manifest and gate import behind confirmation
    if "import_manifest" in st.session_state and st.session_state.get("import_manifest_source") == source_path:
        inventory = st.session_state["import_manifest"]
        grand_total = st.session_state["import_manifest_total"]

        st.markdown("---")
        render_section_header("Pre-Import Manifest", "📋", f"Found {grand_total} notes across {len(inventory)} file(s)")

        # Group files by folder name relative to source path
        source_p = Path(source_path)
        base_dir = source_p if source_p.is_dir() else source_p.parent
        folders: dict[str, list[tuple[str, list[dict]]]] = {}
        for file_path_str, summaries in inventory.items():
            fp = Path(file_path_str)
            try:
                rel = fp.parent.relative_to(base_dir)
                folder_name = str(rel) if str(rel) != "." else "/"
            except ValueError:
                folder_name = "/"
            if folder_name not in folders:
                folders[folder_name] = []
            folders[folder_name].append((fp.name, summaries))

        for folder_name in sorted(folders.keys(), key=str.casefold):
            files_in_folder = folders[folder_name]
            folder_note_count = sum(len(s) for _, s in files_in_folder)
            with st.expander(f"📂 {folder_name} — {len(files_in_folder)} file(s), {folder_note_count} notes"):
                for file_name, summaries in sorted(files_in_folder, key=lambda x: x[0].casefold()):
                    st.markdown(f"**{file_name}** ({len(summaries)} notes)")
                    for s in summaries:
                        created_str = s["created"].strftime("%Y-%m-%d %H:%M") if s["created"] else "no date"
                        st.markdown(f"- {s['title']} ({created_str})")

        st.info(f"Review the manifest above, then click **Start Import** to proceed. Total: **{grand_total}** notes.")

        if st.button("🚀  Start Import", type="primary", key="start_import_confirmed"):
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
                total_notes=grand_total,
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
    total_notes: int | None = None,
):
    """Run the import process."""
    source = Path(source_path)

    # Count notes if not already provided by manifest
    if total_notes is None:
        with st.spinner("Scanning ENEX files..."):
            total_notes = 0
            enex_files = []
            if source.is_file():
                total_notes = count_notes_in_enex(source)
                enex_files = [source]
            else:
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
    render_main_header(
        "Import History",
        "View and manage your past import sessions"
    )

    # Session filter
    sessions = db.get_recent_sessions(limit=50)

    if not sessions:
        st.info("📭 No import sessions found. Start an import to see history here.")
        return

    # Session selector
    session_options = {
        f"Session {s.id} — {s.started_at.strftime('%Y-%m-%d %H:%M')} ({s.status.value})": s.id
        for s in sessions
    }

    selected = st.selectbox("📋  Select Session", options=list(session_options.keys()))
    session_id = session_options[selected]

    session = db.get_session(session_id)

    if session:
        # Session details with styled metrics
        st.markdown("---")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            render_metric_card("Total Notes", session.total_notes, "metric-info")
        with col2:
            render_metric_card("Completed", session.completed_notes, "metric-success")
        with col3:
            render_metric_card("Failed", session.failed_notes, "metric-danger")
        with col4:
            render_metric_card("Skipped", session.skipped_notes, "metric-warning")

        # Session info
        st.markdown("<br>", unsafe_allow_html=True)
        info_col1, info_col2 = st.columns(2)
        with info_col1:
            st.markdown(f"**Source:** `{session.source_path}`")
            st.markdown(f"**Wiki URL:** {session.wiki_url}")
        with info_col2:
            st.markdown(f"**Target Space:** {session.target_space}")
            if session.finished_at:
                duration = session.finished_at - session.started_at
                st.markdown(f"**Duration:** {duration.seconds // 60}m {duration.seconds % 60}s")

        # Per-file breakdown
        st.markdown("---")
        render_section_header("Per-File Breakdown", "📂", "Import results grouped by source ENEX file")

        file_summary = db.get_session_file_summary(session_id)
        if file_summary:
            file_summary_data = []
            for fs in file_summary:
                file_summary_data.append({
                    "Source File": Path(fs["source_file"]).name if fs["source_file"] else "-",
                    "Full Path": fs["source_file"],
                    "Total": fs["total"],
                    "Completed": fs["completed"],
                    "Failed": fs["failed"],
                    "Skipped": fs["skipped"],
                })
            st.dataframe(file_summary_data, use_container_width=True, hide_index=True)

        # Record filters
        st.markdown("---")
        render_section_header("Import Records", "📄", "View individual note import results")

        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            status_filter = st.selectbox(
                "Filter by Status",
                ["All", "Completed", "Failed", "Skipped", "Pending"],
            )

        with filter_col2:
            file_options = ["All Files"] + [fs["source_file"] for fs in file_summary] if file_summary else ["All Files"]
            file_filter = st.selectbox(
                "Filter by File",
                file_options,
            )
            file_filter_value = None if file_filter == "All Files" else file_filter

        status_map = {
            "All": None,
            "Completed": ImportStatus.COMPLETED,
            "Failed": ImportStatus.FAILED,
            "Skipped": ImportStatus.SKIPPED,
            "Pending": ImportStatus.PENDING,
        }

        # Pagination controls
        records_per_page = 500
        page_key = "records_page"
        if page_key not in st.session_state:
            st.session_state[page_key] = 0
        current_page = st.session_state[page_key]

        records = db.get_session_records(
            session_id,
            status=status_map[status_filter],
            source_file=file_filter_value,
            limit=records_per_page + 1,  # fetch one extra to detect if there's a next page
            offset=current_page * records_per_page,
        )

        has_next_page = len(records) > records_per_page
        display_records = records[:records_per_page]

        if display_records:
            # Display as table
            table_data = []
            for r in display_records:
                table_data.append({
                    "Source File": Path(r.source_file).name if r.source_file else "-",
                    "Title": r.note_title[:80] + "..." if len(r.note_title) > 80 else r.note_title,
                    "Identifier": r.note_identifier[:8] if r.note_identifier else "-",
                    "Status": r.status.value,
                    "Page URL": r.page_url or "-",
                    "Attachments": f"{r.attachments_uploaded}/{r.attachments_count}",
                    "Updated": r.updated_at.strftime("%H:%M:%S"),
                })

            st.dataframe(table_data, use_container_width=True)

            # Show full source file path and error details in expanders
            error_records = [r for r in display_records if r.error_message]
            if error_records:
                with st.expander(f"Error Details ({len(error_records)} records with errors)"):
                    for r in error_records:
                        st.markdown(f"**{r.note_title}** (`{r.source_file}`)")
                        st.code(r.error_message, language=None)
                        st.markdown("---")

            # Pagination controls
            pag_col1, pag_col2, pag_col3 = st.columns([1, 2, 1])
            with pag_col1:
                if current_page > 0:
                    if st.button("Previous Page", key="prev_page"):
                        st.session_state[page_key] = current_page - 1
                        st.rerun()
            with pag_col2:
                start_record = current_page * records_per_page + 1
                end_record = start_record + len(display_records) - 1
                st.markdown(f"<div style='text-align:center'>Showing records {start_record}–{end_record} (page {current_page + 1})</div>", unsafe_allow_html=True)
            with pag_col3:
                if has_next_page:
                    if st.button("Next Page", key="next_page"):
                        st.session_state[page_key] = current_page + 1
                        st.rerun()
        else:
            st.info("No records found for the selected filter.")

        # Delete session button
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            if st.button("🗑️  Delete Session", type="secondary", use_container_width=True):
                db.delete_session(session_id)
                st.success("✓ Session deleted!")
                st.rerun()


def render_reconciliation_page(db: ImportDatabase):
    """Render the reconciliation tool page."""
    render_main_header(
        "Reconciliation",
        "Compare ENEX source files against import records to find missing or orphaned notes"
    )

    # Session selector (reuse pattern from history page)
    sessions = db.get_recent_sessions(limit=50)

    if not sessions:
        st.info("No import sessions found. Run an import first.")
        return

    session_options = {
        f"Session {s.id} — {s.started_at.strftime('%Y-%m-%d %H:%M')} ({s.status.value})": s.id
        for s in sessions
    }

    selected = st.selectbox("Select Import Session", options=list(session_options.keys()), key="recon_session")
    session_id = session_options[selected]

    session = db.get_session(session_id)

    # Source path input, pre-filled from session
    default_source = session.source_path if session else ""
    source_path = render_path_chooser(
        label="Source ENEX Path",
        default_value=default_source,
        key_prefix="recon_source",
        help_text="Path to the ENEX file or directory used for this import session",
    )

    if st.button("Run Reconciliation", type="primary"):
        if not source_path or not Path(source_path).exists():
            st.error("Please enter a valid path to an ENEX file or directory.")
            return

        # Step 1: Build ENEX inventory
        with st.spinner("Scanning ENEX files..."):
            try:
                inventory, enex_total = build_enex_inventory(source_path)
            except Exception as e:
                st.error(f"Error scanning ENEX files: {e}")
                return

        # Step 2: Get all import records for this session
        with st.spinner("Loading import records..."):
            records = db.get_session_records(session_id, limit=10000)

        # Step 3: Build identifier sets for comparison
        # ENEX side: generate identifiers
        enex_notes: dict[str, dict] = {}  # identifier -> {title, created, source_file}
        for file_path_str, summaries in inventory.items():
            for s in summaries:
                note_id = generate_note_identifier(s["title"], s["created"])
                enex_notes[note_id] = {
                    "title": s["title"],
                    "created": s["created"],
                    "source_file": file_path_str,
                }

        # DB side: collect identifiers
        db_notes: dict[str, dict] = {}  # identifier -> {title, status, source_file}
        for r in records:
            db_notes[r.note_identifier] = {
                "title": r.note_title,
                "status": r.status.value,
                "source_file": r.source_file,
            }

        enex_ids = set(enex_notes.keys())
        db_ids = set(db_notes.keys())

        # Step 4: Build comparison lists
        in_enex_not_db = enex_ids - db_ids
        in_db_not_enex = db_ids - enex_ids

        # Summary metrics
        st.markdown("---")
        render_section_header("Reconciliation Results", "📊")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            render_metric_card("ENEX Notes", enex_total, "metric-info")
        with col2:
            render_metric_card("DB Records", len(records), "metric-info")
        with col3:
            render_metric_card("Missing from DB", len(in_enex_not_db), "metric-danger" if in_enex_not_db else "metric-success")
        with col4:
            render_metric_card("Orphaned in DB", len(in_db_not_enex), "metric-warning" if in_db_not_enex else "metric-success")

        # Per-file status breakdown
        st.markdown("---")
        render_section_header("Per-File Status Breakdown", "📂")

        file_summary = db.get_session_file_summary(session_id)
        file_summary_map = {fs["source_file"]: fs for fs in file_summary}

        breakdown_data = []
        for file_path_str, summaries in inventory.items():
            db_info = file_summary_map.get(file_path_str, {})
            breakdown_data.append({
                "Source File": Path(file_path_str).name,
                "In ENEX": len(summaries),
                "In DB (Total)": db_info.get("total", 0),
                "Completed": db_info.get("completed", 0),
                "Failed": db_info.get("failed", 0),
                "Skipped": db_info.get("skipped", 0),
            })

        if breakdown_data:
            st.dataframe(breakdown_data, use_container_width=True, hide_index=True)

        # Detail: notes in ENEX but not in DB
        if in_enex_not_db:
            st.markdown("---")
            render_section_header("Missing from Database", "❌", f"{len(in_enex_not_db)} notes in ENEX files were never processed")

            # Group by source file
            missing_by_file: dict[str, list[dict]] = {}
            for note_id in in_enex_not_db:
                info = enex_notes[note_id]
                src = info["source_file"]
                if src not in missing_by_file:
                    missing_by_file[src] = []
                missing_by_file[src].append(info)

            for file_path_str, notes in missing_by_file.items():
                with st.expander(f"{Path(file_path_str).name} — {len(notes)} missing"):
                    for n in notes:
                        created_str = n["created"].strftime("%Y-%m-%d %H:%M") if n["created"] else "no date"
                        st.markdown(f"- **{n['title']}** ({created_str})")

        # Detail: notes in DB but not in ENEX
        if in_db_not_enex:
            st.markdown("---")
            render_section_header("Orphaned Records", "⚠️", f"{len(in_db_not_enex)} records in DB with no matching ENEX note")

            orphan_by_file: dict[str, list[dict]] = {}
            for note_id in in_db_not_enex:
                info = db_notes[note_id]
                src = info["source_file"]
                if src not in orphan_by_file:
                    orphan_by_file[src] = []
                orphan_by_file[src].append(info)

            for file_path_str, notes in orphan_by_file.items():
                with st.expander(f"{Path(file_path_str).name} — {len(notes)} orphaned"):
                    for n in notes:
                        st.markdown(f"- **{n['title']}** (status: {n['status']})")

        if not in_enex_not_db and not in_db_not_enex:
            st.success("All ENEX notes have matching database records. No discrepancies found.")


def render_stats_page(db: ImportDatabase):
    """Render the statistics page."""
    render_main_header(
        "Statistics Dashboard",
        "Overview of all your import activity"
    )

    stats = db.get_stats()

    # Main metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        render_metric_card("Total Processed", stats["total_notes"], "metric-info")

    with col2:
        render_metric_card("Imported", stats["completed"], "metric-success")

    with col3:
        render_metric_card("Failed", stats["failed"], "metric-danger")

    with col4:
        render_metric_card("Sessions", stats["total_sessions"], "")

    # Success rate
    st.markdown("<br>", unsafe_allow_html=True)
    if stats["total_notes"] > 0:
        success_rate = (stats["completed"] / stats["total_notes"]) * 100
        st.markdown(f"### Success Rate: **{success_rate:.1f}%**")
        st.progress(success_rate / 100)
    else:
        st.info("No import data yet. Run your first import to see statistics.")

    # Recent sessions
    st.markdown("---")
    render_section_header("Recent Sessions", "📅", "Your latest import sessions")

    sessions = db.get_recent_sessions(limit=10)

    if sessions:
        table_data = []
        for s in sessions:
            duration = ""
            if s.finished_at:
                delta = s.finished_at - s.started_at
                duration = f"{delta.seconds // 60}m {delta.seconds % 60}s"

            # Add status emoji
            status_emoji = {
                "completed": "✅",
                "failed": "❌",
                "in_progress": "⏳",
                "pending": "⏸️"
            }.get(s.status.value, "")

            table_data.append({
                "ID": s.id,
                "Started": s.started_at.strftime("%Y-%m-%d %H:%M"),
                "Status": f"{status_emoji} {s.status.value}",
                "Total": s.total_notes,
                "Completed": s.completed_notes,
                "Failed": s.failed_notes,
                "Duration": duration or "⏳ In progress",
            })

        st.dataframe(table_data, use_container_width=True, hide_index=True)
    else:
        st.info("📭 No sessions found.")

    # Failed notes summary
    st.markdown("---")
    render_section_header("Recent Failed Imports", "⚠️", "Notes that encountered errors during import")

    failed_records = db.get_all_records(status=ImportStatus.FAILED, limit=20)

    if failed_records:
        for r in failed_records:
            with st.expander(f"❌  {r.note_title}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**Source:** `{r.source_file}`")
                    st.markdown(f"**Time:** {r.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")
                with col2:
                    st.markdown(f"**Error:**")
                    st.code(r.error_message, language=None)
    else:
        st.success("✨ No failed imports! All your notes were imported successfully.")


if __name__ == "__main__":
    main()

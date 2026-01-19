# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Evernote Extractor - A tool for migrating Evernote notes to XWiki with preserved formatting and attachments.

## Project Structure

```
Evernote_Extractor/
├── app.py              # Main Streamlit web application
├── run_app.py          # Launcher script for the web UI
├── cli.py              # Command-line interface
├── converter.py        # Note format conversion (Evernote → XWiki)
├── database.py         # SQLite import tracking
├── enex_parser.py      # ENEX file parsing
├── evernote_api.py     # Evernote API client with OAuth
├── models.py           # Data classes (Note, Attachment, ConvertedPage)
├── progress.py         # Progress tracking utilities
├── xwiki_client.py     # XWiki REST API integration
└── CLAUDE.md           # This file
```

## Running the Application

```bash
# From project root directory
cd "/home/doug/Dropbox/Projects/python Projects/Evernote Extraction"

# Start web UI
streamlit run Evernote_Extractor/app.py

# Or use the launcher script
python Evernote_Extractor/run_app.py
```

## Key Technical Details

- **Framework**: Streamlit for web UI
- **Database**: SQLite for import history tracking
- **Config Storage**: JSON files in `~/.evernote_extractor/`
- **Package Name**: `Evernote_Extractor` (note capitalization)

## Import Notes

When importing modules within the package, use:
```python
from Evernote_Extractor.module_name import ...
```

The app.py file adds the parent directory to sys.path to enable these imports when running with Streamlit.

## UI Design

The web interface uses custom CSS for a professional appearance:
- Purple gradient color scheme
- Dark sidebar with white text
- Card-based layouts for configuration sections
- Styled metric cards for statistics
- Inter font family

## Development Commands

```bash
# Syntax check
python3 -m py_compile Evernote_Extractor/app.py

# Install in development mode
pip install -e .
```

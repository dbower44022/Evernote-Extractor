"""Evernote API client for direct note access."""

import hashlib
import http.server
import json
import threading
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import parse_qs, urlparse

from requests_oauthlib import OAuth1Session

from .models import Attachment, Note

# Evernote API endpoints
EVERNOTE_HOST = "www.evernote.com"
EVERNOTE_SANDBOX_HOST = "sandbox.evernote.com"
YINXIANG_HOST = "app.yinxiang.com"

# OAuth URLs
REQUEST_TOKEN_URL = "https://{host}/oauth"
ACCESS_TOKEN_URL = "https://{host}/oauth"
AUTHORIZE_URL = "https://{host}/OAuth.action"

# Default callback port for OAuth
DEFAULT_CALLBACK_PORT = 10500


@dataclass
class EvernoteCredentials:
    """Evernote API credentials."""

    consumer_key: str
    consumer_secret: str
    sandbox: bool = False

    @property
    def host(self) -> str:
        """Get the appropriate Evernote host."""
        if self.sandbox:
            return EVERNOTE_SANDBOX_HOST
        return EVERNOTE_HOST


@dataclass
class EvernoteNotebook:
    """Represents an Evernote notebook."""

    guid: str
    name: str
    note_count: int = 0
    stack: str | None = None


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler to receive OAuth callback."""

    oauth_response: dict = {}

    def do_GET(self):
        """Handle GET request from OAuth callback."""
        # Parse the query parameters
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        # Store the response
        OAuthCallbackHandler.oauth_response = {
            k: v[0] if len(v) == 1 else v
            for k, v in params.items()
        }

        # Send success response
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

        html = """
        <html>
        <head><title>Authentication Successful</title></head>
        <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
            <h1>✅ Authentication Successful!</h1>
            <p>You can close this window and return to the application.</p>
            <script>window.close();</script>
        </body>
        </html>
        """
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        """Suppress logging."""
        pass


class EvernoteOAuth:
    """Handle Evernote OAuth authentication."""

    def __init__(self, credentials: EvernoteCredentials, callback_port: int = DEFAULT_CALLBACK_PORT):
        self.credentials = credentials
        self.callback_port = callback_port
        self.callback_url = f"http://localhost:{callback_port}/callback"
        self.host = credentials.host

    def get_request_token_url(self) -> str:
        return REQUEST_TOKEN_URL.format(host=self.host)

    def get_access_token_url(self) -> str:
        return ACCESS_TOKEN_URL.format(host=self.host)

    def get_authorize_url(self) -> str:
        return AUTHORIZE_URL.format(host=self.host)

    def authenticate(self, open_browser: bool = True) -> str | None:
        """
        Perform OAuth authentication flow.

        Returns the access token if successful, None otherwise.
        """
        try:
            # Create OAuth session
            oauth = OAuth1Session(
                self.credentials.consumer_key,
                client_secret=self.credentials.consumer_secret,
                callback_uri=self.callback_url,
            )

            # Get request token
            fetch_response = oauth.fetch_request_token(self.get_request_token_url())
            resource_owner_key = fetch_response.get("oauth_token")
            resource_owner_secret = fetch_response.get("oauth_token_secret")

            # Get authorization URL
            authorization_url = oauth.authorization_url(self.get_authorize_url())

            # Start local server to receive callback
            server = http.server.HTTPServer(
                ("localhost", self.callback_port),
                OAuthCallbackHandler,
            )
            server.timeout = 300  # 5 minute timeout

            # Clear previous response
            OAuthCallbackHandler.oauth_response = {}

            # Open browser for user authentication
            if open_browser:
                webbrowser.open(authorization_url)

            # Wait for callback (blocking)
            server.handle_request()
            server.server_close()

            # Check for OAuth response
            if not OAuthCallbackHandler.oauth_response:
                return None

            oauth_verifier = OAuthCallbackHandler.oauth_response.get("oauth_verifier")
            if not oauth_verifier:
                return None

            # Exchange for access token
            oauth = OAuth1Session(
                self.credentials.consumer_key,
                client_secret=self.credentials.consumer_secret,
                resource_owner_key=resource_owner_key,
                resource_owner_secret=resource_owner_secret,
                verifier=oauth_verifier,
            )

            oauth_tokens = oauth.fetch_access_token(self.get_access_token_url())
            access_token = oauth_tokens.get("oauth_token")

            return access_token

        except Exception as e:
            print(f"OAuth authentication failed: {e}")
            return None


class EvernoteClient:
    """Client for accessing Evernote API."""

    def __init__(self, access_token: str, sandbox: bool = False):
        """
        Initialize Evernote client.

        Args:
            access_token: OAuth access token
            sandbox: Use sandbox environment
        """
        self.access_token = access_token
        self.sandbox = sandbox
        self.host = EVERNOTE_SANDBOX_HOST if sandbox else EVERNOTE_HOST

        # Initialize Evernote SDK client
        from evernote.api.client import EvernoteClient as SDKClient

        self.client = SDKClient(token=access_token, sandbox=sandbox)
        self.note_store = self.client.get_note_store()
        self.user_store = self.client.get_user_store()

        # Cache for tags
        self._tags_cache: dict[str, str] = {}

    def get_user_info(self) -> dict:
        """Get information about the authenticated user."""
        try:
            user = self.user_store.getUser()
            return {
                "username": user.username,
                "email": user.email,
                "name": user.name,
                "id": user.id,
            }
        except Exception as e:
            return {"error": str(e)}

    def list_notebooks(self) -> list[EvernoteNotebook]:
        """List all notebooks in the account."""
        notebooks = []

        try:
            raw_notebooks = self.note_store.listNotebooks()

            for nb in raw_notebooks:
                # Get note count for this notebook
                from evernote.edam.notestore.ttypes import NoteFilter, NotesMetadataResultSpec

                note_filter = NoteFilter(notebookGuid=nb.guid)
                result_spec = NotesMetadataResultSpec(includeTitle=False)

                try:
                    metadata = self.note_store.findNotesMetadata(
                        note_filter, 0, 1, result_spec
                    )
                    note_count = metadata.totalNotes
                except Exception:
                    note_count = 0

                notebooks.append(EvernoteNotebook(
                    guid=nb.guid,
                    name=nb.name,
                    note_count=note_count,
                    stack=nb.stack,
                ))

            return notebooks

        except Exception as e:
            print(f"Error listing notebooks: {e}")
            return []

    def _load_tags(self) -> None:
        """Load all tags into cache."""
        if self._tags_cache:
            return

        try:
            tags = self.note_store.listTags()
            self._tags_cache = {tag.guid: tag.name for tag in tags}
        except Exception:
            pass

    def _get_tag_names(self, tag_guids: list[str] | None) -> list[str]:
        """Convert tag GUIDs to tag names."""
        if not tag_guids:
            return []

        self._load_tags()
        return [self._tags_cache.get(guid, "") for guid in tag_guids if guid in self._tags_cache]

    def get_notes_from_notebook(
        self,
        notebook_guid: str,
        notebook_name: str = "",
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> Iterator[Note]:
        """
        Download all notes from a notebook.

        Args:
            notebook_guid: GUID of the notebook
            notebook_name: Name of the notebook (for setting note.notebook)
            progress_callback: Optional callback(current, total, note_title)

        Yields:
            Note objects
        """
        from evernote.edam.notestore.ttypes import NoteFilter, NotesMetadataResultSpec

        # Set up filter for this notebook
        note_filter = NoteFilter(notebookGuid=notebook_guid)
        result_spec = NotesMetadataResultSpec(
            includeTitle=True,
            includeCreated=True,
            includeUpdated=True,
            includeTagGuids=True,
        )

        # Get total count first
        offset = 0
        page_size = 100

        try:
            metadata = self.note_store.findNotesMetadata(
                note_filter, 0, 1, result_spec
            )
            total_notes = metadata.totalNotes
        except Exception as e:
            print(f"Error getting note count: {e}")
            return

        # Iterate through all notes
        processed = 0
        while offset < total_notes:
            try:
                metadata = self.note_store.findNotesMetadata(
                    note_filter, offset, page_size, result_spec
                )

                for note_meta in metadata.notes:
                    try:
                        # Get the full note with content and resources
                        note = self._download_note(note_meta.guid)
                        if note:
                            note.notebook = notebook_name

                            # Add tags
                            note.tags = self._get_tag_names(note_meta.tagGuids)

                            processed += 1
                            if progress_callback:
                                progress_callback(processed, total_notes, note.title)

                            yield note

                    except Exception as e:
                        print(f"Error downloading note {note_meta.title}: {e}")
                        processed += 1
                        continue

                offset += page_size

            except Exception as e:
                print(f"Error fetching notes: {e}")
                break

    def _download_note(self, note_guid: str) -> Note | None:
        """Download a single note with all its content and attachments."""
        try:
            # Get note with content and resources
            raw_note = self.note_store.getNote(
                note_guid,
                True,   # withContent
                True,   # withResourcesData
                True,   # withResourcesRecognition
                True,   # withResourcesAlternateData
            )

            # Parse created/updated timestamps
            created = None
            updated = None
            if raw_note.created:
                created = datetime.fromtimestamp(raw_note.created / 1000)
            if raw_note.updated:
                updated = datetime.fromtimestamp(raw_note.updated / 1000)

            # Extract attachments
            attachments = []
            if raw_note.resources:
                for resource in raw_note.resources:
                    attachment = self._parse_resource(resource)
                    if attachment:
                        attachments.append(attachment)

            # Get source URL from attributes
            source_url = None
            if raw_note.attributes and raw_note.attributes.sourceURL:
                source_url = raw_note.attributes.sourceURL

            return Note(
                title=raw_note.title or "Untitled",
                content=raw_note.content or "",
                created=created,
                updated=updated,
                tags=[],  # Tags are added by caller
                attachments=attachments,
                source_url=source_url,
                notebook=None,  # Set by caller
            )

        except Exception as e:
            print(f"Error downloading note {note_guid}: {e}")
            return None

    def _parse_resource(self, resource) -> Attachment | None:
        """Parse an Evernote resource into an Attachment."""
        try:
            if not resource.data or not resource.data.body:
                return None

            data = resource.data.body
            mime_type = resource.mime or "application/octet-stream"

            # Calculate hash
            hash_value = hashlib.md5(data).hexdigest()

            # Get filename
            filename = None
            if resource.attributes and resource.attributes.fileName:
                filename = resource.attributes.fileName

            if not filename:
                # Generate from hash and mime type
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

        except Exception as e:
            print(f"Error parsing resource: {e}")
            return None


def save_token(token: str, path: Path | None = None) -> None:
    """Save access token to file."""
    if path is None:
        path = Path.home() / ".evernote_extractor" / "evernote_token.json"

    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w") as f:
        json.dump({"access_token": token}, f)


def load_token(path: Path | None = None) -> str | None:
    """Load access token from file."""
    if path is None:
        path = Path.home() / ".evernote_extractor" / "evernote_token.json"

    if not path.exists():
        return None

    try:
        with open(path) as f:
            data = json.load(f)
            return data.get("access_token")
    except (json.JSONDecodeError, IOError):
        return None


def delete_token(path: Path | None = None) -> None:
    """Delete saved access token."""
    if path is None:
        path = Path.home() / ".evernote_extractor" / "evernote_token.json"

    if path.exists():
        path.unlink()

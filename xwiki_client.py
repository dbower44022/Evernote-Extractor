"""XWiki REST API client for uploading pages and attachments."""

import base64
import time
from dataclasses import dataclass
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import ConvertedPage


@dataclass
class UploadResult:
    """Result of an upload operation."""

    success: bool
    page_url: str | None = None
    error: str | None = None
    attachments_uploaded: int = 0
    attachments_failed: int = 0


class XWikiClient:
    """Client for XWiki REST API."""

    def __init__(
        self,
        wiki_url: str,
        username: str,
        password: str,
        wiki_name: str = "xwiki",
        rate_limit_delay: float = 0.5,
        max_retries: int = 3,
    ):
        """
        Initialize XWiki client.

        Args:
            wiki_url: Base URL of the XWiki instance (e.g., https://yourwiki.xwiki.cloud)
            username: XWiki username for authentication
            password: XWiki password for authentication
            wiki_name: Name of the wiki (default: xwiki)
            rate_limit_delay: Delay between requests in seconds
            max_retries: Maximum number of retries for failed requests
        """
        self.wiki_url = wiki_url.rstrip("/")
        self.username = username
        self.password = password
        self.wiki_name = wiki_name
        self.rate_limit_delay = rate_limit_delay

        # Set up session with retry logic
        self.session = requests.Session()

        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Set HTTP Basic Authentication
        self.session.auth = (username, password)
        self.session.headers.update({
            "Accept": "application/json",
        })

        # Form token for CSRF protection (fetched on first request)
        self._form_token: str | None = None

    def _get_rest_url(self) -> str:
        """Get the REST API base URL."""
        return f"{self.wiki_url}/rest/wikis/{self.wiki_name}"

    def _get_form_token(self) -> str | None:
        """Fetch the CSRF form token from XWiki."""
        if self._form_token:
            return self._form_token

        try:
            response = self.session.get(self._get_rest_url())
            self._form_token = response.headers.get("XWiki-Form-Token")
            return self._form_token
        except requests.RequestException:
            return None

    def _get_auth_header(self) -> str:
        """Get the Basic Authorization header value."""
        auth_string = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        return f"Basic {auth_string}"

    def _get_write_headers(self, content_type: str = "application/xml") -> dict:
        """Get headers for write operations."""
        # Use explicit Authorization header instead of session.auth
        # This matches the working curl behavior
        headers = {
            "Content-Type": content_type,
            "Authorization": self._get_auth_header(),
        }
        return headers

    def _space_to_url_path(self, space: str) -> str:
        """Convert a space path (e.g., 'Parent.Child') to URL path format."""
        # XWiki REST API uses /spaces/Parent/spaces/Child format for nested spaces
        parts = space.split(".")
        path_parts = []
        for part in parts:
            path_parts.append(f"spaces/{part}")
        return "/".join(path_parts)

    def _rate_limit(self) -> None:
        """Apply rate limiting delay."""
        if self.rate_limit_delay > 0:
            time.sleep(self.rate_limit_delay)

    def test_connection(self) -> bool:
        """Test the connection to XWiki."""
        result = self.test_connection_detailed()
        return result["success"]

    def test_connection_detailed(self) -> dict:
        """Test the connection to XWiki with detailed results."""
        url = self._get_rest_url()
        try:
            response = self.session.get(url)
            return {
                "success": response.status_code == 200,
                "status_code": response.status_code,
                "url_tested": url,
                "error": None if response.status_code == 200 else f"HTTP {response.status_code}",
            }
        except requests.RequestException as e:
            return {
                "success": False,
                "status_code": None,
                "url_tested": url,
                "error": str(e),
            }

    def check_user_info(self) -> dict:
        """Get information about the authenticated user."""
        results = {}

        # Try the base REST endpoint
        try:
            response = self.session.get(f"{self.wiki_url}/rest")
            results["rest_root"] = {
                "status": response.status_code,
                "form_token": response.headers.get("XWiki-Form-Token", "Not found"),
            }
        except requests.RequestException as e:
            results["rest_root"] = {"error": str(e)}

        # Try to get current user via whoami-style endpoint
        try:
            response = self.session.get(f"{self._get_rest_url()}")
            results["wiki_info"] = {
                "status": response.status_code,
                "response": response.text[:300] if response.text else "Empty",
            }
        except requests.RequestException as e:
            results["wiki_info"] = {"error": str(e)}

        # Check if we can read an existing page (Main.WebHome)
        try:
            response = self.session.get(f"{self._get_rest_url()}/spaces/Main/pages/WebHome")
            results["read_test"] = {
                "status": response.status_code,
                "can_read": response.status_code == 200,
            }
        except requests.RequestException as e:
            results["read_test"] = {"error": str(e)}

        return results

    def test_page_creation(self, space: str, page_name: str = "TestPage") -> dict:
        """Test if we can create a simple test page."""
        space_path = self._space_to_url_path(space)
        # Use nested pages structure: /spaces/Parent/spaces/PageName/pages/WebHome
        url = f"{self._get_rest_url()}/{space_path}/spaces/{page_name}/pages/WebHome"

        # Use exact same format as curl that worked
        test_xml = '<?xml version="1.0" encoding="UTF-8"?><page xmlns="http://www.xwiki.org"><title>Test Page</title><content>Test from Python</content></page>'

        try:
            # Make a simple PUT request with explicit Authorization header
            response = requests.put(
                url,
                data=test_xml,
                headers=self._get_write_headers("application/xml"),
            )

            return {
                "success": response.status_code in (200, 201, 202),
                "status_code": response.status_code,
                "url": url,
                "response": response.text[:500] if response.text else "Empty",
                "auth_user": self.username,
            }
        except requests.RequestException as e:
            return {"error": str(e), "url": url}

    def create_or_update_page(
        self,
        page: ConvertedPage,
        dry_run: bool = False,
    ) -> UploadResult:
        """
        Create or update a page in XWiki.

        Args:
            page: The converted page to upload
            dry_run: If True, don't actually upload

        Returns:
            UploadResult with success status and details
        """
        space_path = self._space_to_url_path(page.space)
        page_name = page.page_name
        # Use nested pages structure: /spaces/Parent/spaces/PageName/pages/WebHome
        url = f"{self._get_rest_url()}/{space_path}/spaces/{page_name}/pages/WebHome"

        if dry_run:
            return UploadResult(
                success=True,
                page_url=f"{self.wiki_url}/wiki/{self.wiki_name}/{page.space.replace('.', '/')}/{page_name}",
            )

        # Build the page XML
        page_xml = self._build_page_xml(page)

        try:
            self._rate_limit()

            response = requests.put(
                url,
                data=page_xml.encode('utf-8'),
                headers=self._get_write_headers("application/xml; charset=UTF-8"),
            )

            if response.status_code in (200, 201, 202):
                page_url = f"{self.wiki_url}/wiki/{self.wiki_name}/{page.space.replace('.', '/')}/{page_name}"

                # Upload attachments
                attachments_uploaded = 0
                attachments_failed = 0

                for attachment in page.attachments:
                    if self._upload_attachment(page.space, page_name, attachment):
                        attachments_uploaded += 1
                    else:
                        attachments_failed += 1

                # Add tags
                if page.tags:
                    self._add_tags(page.space, page_name, page.tags)

                # Verify page was actually created
                if self.page_exists(page.space, page_name):
                    return UploadResult(
                        success=True,
                        page_url=page_url,
                        attachments_uploaded=attachments_uploaded,
                        attachments_failed=attachments_failed,
                    )
                else:
                    return UploadResult(
                        success=False,
                        error="Page creation reported success but verification failed - page not found",
                    )
            else:
                # Include more details for debugging
                error_detail = f"HTTP {response.status_code}: {response.text[:500]}"
                return UploadResult(
                    success=False,
                    error=f"{error_detail} | URL: {url} | Form-Token: {self._form_token is not None}",
                )

        except requests.RequestException as e:
            return UploadResult(
                success=False,
                error=f"Request error: {e} | URL: {url}",
            )

    def _build_page_xml(self, page: ConvertedPage) -> str:
        """Build XML representation of a page for the REST API."""
        # Escape XML special characters in content
        content = (
            page.content
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

        title = (
            page.title
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<page xmlns="http://www.xwiki.org">
  <title>{title}</title>
  <syntax>xwiki/2.1</syntax>
  <content>{content}</content>
</page>"""

    def _upload_attachment(
        self,
        space: str,
        page_name: str,
        attachment: Any,
    ) -> bool:
        """Upload an attachment to a page."""
        space_path = self._space_to_url_path(space)
        # Use nested pages structure
        url = f"{self._get_rest_url()}/{space_path}/spaces/{page_name}/pages/WebHome/attachments/{attachment.filename}"

        try:
            self._rate_limit()

            response = requests.put(
                url,
                data=attachment.data,
                headers=self._get_write_headers(attachment.mime_type),
            )

            return response.status_code in (200, 201, 202)

        except requests.RequestException:
            return False

    def _add_tags(self, space: str, page_name: str, tags: list[str]) -> bool:
        """Add tags to a page."""
        space_path = self._space_to_url_path(space)
        # Use nested pages structure
        url = f"{self._get_rest_url()}/{space_path}/spaces/{page_name}/pages/WebHome/tags"

        # Build tags XML
        tags_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<tags xmlns="http://www.xwiki.org">\n'
        for tag in tags:
            safe_tag = tag.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            tags_xml += f"  <tag><name>{safe_tag}</name></tag>\n"
        tags_xml += "</tags>"

        try:
            self._rate_limit()

            response = requests.put(
                url,
                data=tags_xml.encode('utf-8'),
                headers=self._get_write_headers("application/xml; charset=UTF-8"),
            )

            return response.status_code in (200, 201, 202)

        except requests.RequestException:
            return False

    def page_exists(self, space: str, page_name: str) -> bool:
        """Check if a page already exists."""
        space_path = self._space_to_url_path(space)
        # Use nested pages structure
        url = f"{self._get_rest_url()}/{space_path}/spaces/{page_name}/pages/WebHome"

        try:
            response = requests.get(
                url,
                headers={"Authorization": self._get_auth_header()},
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def delete_page(self, space: str, page_name: str) -> bool:
        """Delete a page (use with caution)."""
        space_path = self._space_to_url_path(space)
        # Use nested pages structure
        url = f"{self._get_rest_url()}/{space_path}/spaces/{page_name}/pages/WebHome"

        try:
            self._rate_limit()
            response = self.session.delete(url)
            return response.status_code in (200, 204)
        except requests.RequestException:
            return False

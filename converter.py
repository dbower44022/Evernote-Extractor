"""Convert ENML (Evernote Markup Language) to XWiki 2.1 syntax."""

import hashlib
import re
from html import unescape
from io import StringIO
from urllib.parse import urlparse

import requests
from lxml import etree

from .models import Attachment, ConvertedPage, Note


def download_image(url: str, timeout: int = 10) -> Attachment | None:
    """Download an image from a URL and return as an Attachment."""
    try:
        response = requests.get(url, timeout=timeout, stream=True)
        response.raise_for_status()

        # Get content type
        content_type = response.headers.get("Content-Type", "image/png")
        if ";" in content_type:
            content_type = content_type.split(";")[0].strip()

        # Only process images
        if not content_type.startswith("image/"):
            return None

        # Read the data
        data = response.content

        # Generate hash
        hash_value = hashlib.md5(data).hexdigest()

        # Generate filename from URL or hash
        parsed_url = urlparse(url)
        path = parsed_url.path
        if path and "/" in path:
            filename = path.split("/")[-1]
            # Clean up filename
            filename = re.sub(r'[^\w\-_.]', '_', filename)
        else:
            filename = hash_value

        # Ensure proper extension
        ext_map = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/svg+xml": ".svg",
            "image/bmp": ".bmp",
        }

        expected_ext = ext_map.get(content_type, ".png")
        if not filename.lower().endswith(expected_ext):
            # Check if it has any image extension
            has_ext = any(filename.lower().endswith(e) for e in ext_map.values())
            if not has_ext:
                filename = f"{filename}{expected_ext}"

        return Attachment(
            filename=filename,
            mime_type=content_type,
            data=data,
            hash=hash_value,
        )
    except Exception:
        return None


class ENMLToXWikiConverter:
    """Converts ENML content to XWiki 2.1 syntax."""

    def __init__(self, note: Note, download_external_images: bool = True):
        self.note = note
        self.output = StringIO()
        self.list_stack: list[str] = []  # Track nested list types
        self.in_table = False
        self.table_rows: list[list[str]] = []
        self.current_row: list[str] = []
        self.download_external_images = download_external_images
        # Downloaded images from external URLs
        self.downloaded_images: list[Attachment] = []
        # Track filenames to avoid duplicates
        self.used_filenames: set[str] = set()
        # Build hash lookup (normalized to lowercase, no dashes)
        self.attachment_hash_map: dict[str, Attachment] = {}
        for att in note.attachments:
            normalized_hash = att.hash.lower().replace("-", "")
            self.attachment_hash_map[normalized_hash] = att
            self.used_filenames.add(att.filename.lower())

    def _find_attachment_by_hash(self, hash_value: str) -> Attachment | None:
        """Find attachment by hash, handling various hash formats."""
        if not hash_value:
            return None
        normalized = hash_value.lower().replace("-", "")
        return self.attachment_hash_map.get(normalized)

    def convert(self) -> str:
        """Convert the note's ENML content to XWiki syntax."""
        content = self.note.content

        if not content:
            return ""

        # ENML is wrapped in <?xml ...> and <!DOCTYPE ...> declarations
        # Parse the ENML content
        try:
            # Remove XML declaration and DOCTYPE if present
            content = re.sub(r'<\?xml[^?]*\?>', '', content)
            content = re.sub(r'<!DOCTYPE[^>]*>', '', content)
            content = content.strip()

            # Try XML parser first to preserve custom ENML tags
            try:
                parser = etree.XMLParser(recover=True, huge_tree=True)
                root = etree.fromstring(content.encode('utf-8'), parser)
            except Exception:
                # Fallback to HTML parser
                parser = etree.HTMLParser()
                tree = etree.parse(StringIO(content), parser)
                root = tree.getroot()

            # Find the en-note element or body
            en_note = root.find(".//{*}en-note")
            if en_note is None:
                en_note = root.find(".//en-note")
            if en_note is None:
                en_note = root.find(".//body")
            if en_note is None:
                en_note = root

            self._process_element(en_note)

        except etree.XMLSyntaxError:
            # Fallback: strip HTML tags and return plain text
            return self._strip_html(content)

        result = self.output.getvalue()

        # Clean up excessive newlines
        result = re.sub(r'\n{3,}', '\n\n', result)
        result = result.strip()

        return result

    def _get_tag_name(self, element: etree._Element) -> str:
        """Get the local tag name, stripping any namespace."""
        tag = element.tag if element.tag else ""
        # Strip namespace if present (e.g., {http://...}tagname -> tagname)
        if tag.startswith("{"):
            tag = tag.split("}", 1)[-1]
        return tag.lower()

    def _process_element(self, element: etree._Element, depth: int = 0) -> None:
        """Process an element and its children."""
        tag = self._get_tag_name(element)

        # Inline formatting tags - handle specially to preserve text flow
        if tag in ("b", "strong"):
            self._handle_inline_format(element, "**", "**")
            return
        elif tag in ("i", "em"):
            self._handle_inline_format(element, "//", "//")
            return
        elif tag == "u":
            self._handle_inline_format(element, "__", "__")
            return
        elif tag in ("s", "strike", "del"):
            self._handle_inline_format(element, "--", "--")
            return
        elif tag == "a":
            self._handle_link(element)
            return
        elif tag == "en-media":
            self._handle_media(element)
            if element.tail:
                self._write_text(element.tail)
            return
        elif tag == "img":
            self._handle_image(element)
            if element.tail:
                self._write_text(element.tail)
            return
        elif tag == "br":
            self.output.write("\n")
            if element.tail:
                self._write_text(element.tail)
            return
        elif tag == "en-todo":
            self._handle_todo(element)
            if element.tail:
                self._write_text(element.tail)
            return

        # Block-level elements
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._handle_heading(element, int(tag[1]))
        elif tag == "ul":
            self._handle_list(element, ordered=False)
        elif tag == "ol":
            self._handle_list(element, ordered=True)
        elif tag == "li":
            self._handle_list_item(element)
        elif tag == "hr":
            self.output.write("\n----\n")
        elif tag in ("p", "div"):
            self._handle_block(element)
        elif tag == "table":
            self._handle_table(element)
        elif tag == "tr":
            self._handle_table_row(element)
        elif tag in ("td", "th"):
            self._handle_table_cell(element, is_header=(tag == "th"))
        elif tag == "blockquote":
            self._handle_blockquote(element)
        elif tag in ("code", "pre"):
            self._handle_code(element)
        elif tag == "en-crypt":
            self._handle_encrypted(element)
        elif tag == "span":
            # Check for style-based formatting
            self._handle_span(element)
        else:
            # For unknown tags, process text and children
            if element.text:
                self._write_text(element.text)
            for child in element:
                self._process_element(child, depth + 1)

        # Handle tail text (text after the closing tag)
        if element.tail:
            self._write_text(element.tail)

    def _write_text(self, text: str) -> None:
        """Write text, handling HTML entities."""
        if text:
            # Decode HTML entities
            text = unescape(text)
            # Escape XWiki special characters
            text = self._escape_xwiki(text)
            self.output.write(text)

    def _escape_xwiki(self, text: str) -> str:
        """Escape special XWiki characters in regular text."""
        # Only escape when not in a special context
        # XWiki uses ~~ for escaping
        # We need to be careful not to over-escape
        return text

    def _handle_inline_format(self, element: etree._Element, prefix: str, suffix: str) -> None:
        """Handle inline formatting (bold, italic, etc.) with proper text flow."""
        self.output.write(prefix)

        # Write element's text content
        if element.text:
            self._write_text(element.text)

        # Process child elements
        for child in element:
            self._process_element(child)

        self.output.write(suffix)

        # Handle tail text (text after this element)
        if element.tail:
            self._write_text(element.tail)

    def _handle_span(self, element: etree._Element) -> None:
        """Handle span elements, checking for style-based formatting."""
        style = element.get("style", "")

        # Detect formatting from style
        prefix = ""
        suffix = ""

        if "font-weight" in style and ("bold" in style or "700" in style or "800" in style or "900" in style):
            prefix += "**"
            suffix = "**" + suffix
        if "font-style" in style and "italic" in style:
            prefix += "//"
            suffix = "//" + suffix
        if "text-decoration" in style:
            if "underline" in style:
                prefix += "__"
                suffix = "__" + suffix
            if "line-through" in style:
                prefix += "--"
                suffix = "--" + suffix

        if prefix:
            self.output.write(prefix)

        if element.text:
            self._write_text(element.text)

        for child in element:
            self._process_element(child)

        if suffix:
            self.output.write(suffix)

        if element.tail:
            self._write_text(element.tail)

    def _handle_heading(self, element: etree._Element, level: int) -> None:
        """Convert heading to XWiki syntax."""
        # XWiki headings: = H1 =, == H2 ==, etc.
        equals = "=" * level
        self.output.write(f"\n{equals} ")

        # Get text content
        text = self._get_element_text(element)
        self.output.write(text)

        self.output.write(f" {equals}\n")

    def _handle_link(self, element: etree._Element) -> None:
        """Convert hyperlink to XWiki syntax."""
        href = element.get("href", "")
        text = self._get_element_text(element)

        if href:
            if text and text != href:
                # [[label>>url]]
                self.output.write(f"[[{text}>>{href}]]")
            else:
                # [[url]]
                self.output.write(f"[[{href}]]")
        else:
            self._write_text(text)

        # Handle tail text
        if element.tail:
            self._write_text(element.tail)

    def _handle_list(self, element: etree._Element, ordered: bool) -> None:
        """Handle ordered and unordered lists."""
        list_type = "1." if ordered else "*"
        self.list_stack.append(list_type)

        self.output.write("\n")
        for child in element:
            self._process_element(child)

        self.list_stack.pop()
        if not self.list_stack:
            self.output.write("\n")

    def _handle_list_item(self, element: etree._Element) -> None:
        """Handle list items."""
        if self.list_stack:
            # Build prefix based on nesting depth
            prefix = ""
            for i, list_type in enumerate(self.list_stack):
                if list_type == "1.":
                    prefix += "1."
                else:
                    prefix += "*"

            self.output.write(f"{prefix} ")

        # Write element's text
        if element.text:
            self._write_text(element.text)

        # Process children
        for child in element:
            tag = self._get_tag_name(child)
            if tag in ("ul", "ol"):
                self.output.write("\n")
                self._process_element(child)
            else:
                self._process_element(child)

        self.output.write("\n")

    def _handle_block(self, element: etree._Element) -> None:
        """Handle block elements like div and p."""
        # Add newline before block if needed
        current = self.output.getvalue()
        if current and not current.endswith("\n"):
            self.output.write("\n")

        # Write element's text content
        if element.text:
            self._write_text(element.text)

        # Process children
        for child in element:
            self._process_element(child)

        # Add newline after block
        self.output.write("\n")

    def _handle_media(self, element: etree._Element) -> None:
        """Handle en-media elements (attachments in ENML)."""
        # Try different attribute names (case variations)
        media_hash = (
            element.get("hash") or
            element.get("Hash") or
            element.get("HASH") or
            ""
        )
        media_type = (
            element.get("type") or
            element.get("Type") or
            element.get("TYPE") or
            ""
        )

        if not media_hash:
            # Try to get from all attributes
            for key, value in element.attrib.items():
                if key.lower() == "hash":
                    media_hash = value
                    break

        if not media_hash:
            return

        # Find the attachment by hash using normalized lookup
        attachment = self._find_attachment_by_hash(media_hash)

        if attachment:
            filename = attachment.filename
            if attachment.is_image:
                # XWiki image syntax with width parameter for better display
                self.output.write(f"[[image:{filename}]]")
            else:
                # XWiki attachment link
                self.output.write(f"[[{filename}>>attach:{filename}]]")
        else:
            # Attachment not found - log the hash for debugging
            short_hash = media_hash[:8] if len(media_hash) > 8 else media_hash
            self.output.write(f"[Missing attachment: {short_hash}...]")

    def _handle_image(self, element: etree._Element) -> None:
        """Handle img elements - download external images and store as attachments."""
        src = element.get("src", "")
        alt = element.get("alt", "")

        if src.startswith("data:"):
            # Data URI - try to decode and save as attachment
            attachment = self._decode_data_uri(src)
            if attachment:
                self.downloaded_images.append(attachment)
                self.output.write(f"[[image:{attachment.filename}]]")
            else:
                self.output.write(f"[Image: {alt or 'embedded data'}]")
        elif src.startswith(("http://", "https://")):
            # External URL - download and save as attachment
            if self.download_external_images:
                attachment = download_image(src)
                if attachment:
                    # Ensure unique filename
                    filename = self._get_unique_filename(attachment.filename)
                    attachment = Attachment(
                        filename=filename,
                        mime_type=attachment.mime_type,
                        data=attachment.data,
                        hash=attachment.hash,
                    )
                    self.downloaded_images.append(attachment)
                    self.used_filenames.add(filename.lower())
                    self.output.write(f"[[image:{filename}]]")
                else:
                    # Failed to download - keep as external link with note
                    self.output.write(f"[[image:{src}]]")
                    self.output.write(f" //(external image)//" )
            else:
                # Not downloading - just reference the URL
                self.output.write(f"[[image:{src}]]")
        elif src:
            # Relative or other URL - keep as-is
            self.output.write(f"[[image:{src}]]")

    def _decode_data_uri(self, data_uri: str) -> Attachment | None:
        """Decode a data URI into an Attachment."""
        import base64

        try:
            # Format: data:image/png;base64,iVBORw0KGgo...
            if not data_uri.startswith("data:"):
                return None

            header, data = data_uri.split(",", 1)
            mime_type = header.split(":")[1].split(";")[0]

            if not mime_type.startswith("image/"):
                return None

            image_data = base64.b64decode(data)
            hash_value = hashlib.md5(image_data).hexdigest()

            ext_map = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/gif": ".gif",
                "image/webp": ".webp",
            }
            ext = ext_map.get(mime_type, ".png")
            filename = f"embedded_{hash_value[:8]}{ext}"

            return Attachment(
                filename=filename,
                mime_type=mime_type,
                data=image_data,
                hash=hash_value,
            )
        except Exception:
            return None

    def _get_unique_filename(self, filename: str) -> str:
        """Get a unique filename, adding suffix if needed."""
        if filename.lower() not in self.used_filenames:
            return filename

        base, ext = filename.rsplit(".", 1) if "." in filename else (filename, "")
        counter = 1
        while True:
            new_name = f"{base}_{counter}.{ext}" if ext else f"{base}_{counter}"
            if new_name.lower() not in self.used_filenames:
                return new_name
            counter += 1

    def _handle_table(self, element: etree._Element) -> None:
        """Handle table elements."""
        self.in_table = True
        self.table_rows = []

        # Process table content
        for child in element:
            if child.tag.lower() in ("thead", "tbody", "tfoot"):
                for row in child:
                    self._process_element(row)
            else:
                self._process_element(child)

        # Write the table in XWiki format
        self.output.write("\n")
        for row in self.table_rows:
            self.output.write("|")
            self.output.write("|".join(row))
            self.output.write("\n")
        self.output.write("\n")

        self.in_table = False
        self.table_rows = []

    def _handle_table_row(self, element: etree._Element) -> None:
        """Handle table row elements."""
        self.current_row = []

        for child in element:
            self._process_element(child)

        if self.current_row:
            self.table_rows.append(self.current_row)
        self.current_row = []

    def _handle_table_cell(self, element: etree._Element, is_header: bool = False) -> None:
        """Handle table cell elements."""
        text = self._get_element_text(element)

        if is_header:
            # XWiki header cells use = prefix
            self.current_row.append(f"={text}")
        else:
            self.current_row.append(text)

    def _handle_blockquote(self, element: etree._Element) -> None:
        """Handle blockquote elements."""
        text = self._get_element_text(element)
        lines = text.split("\n")

        self.output.write("\n")
        for line in lines:
            self.output.write(f"> {line}\n")
        self.output.write("\n")

    def _handle_code(self, element: etree._Element) -> None:
        """Handle code and pre elements."""
        text = element.text or ""

        if element.tag.lower() == "pre" or "\n" in text:
            # Code block
            self.output.write("\n{{code}}\n")
            self.output.write(text)
            self.output.write("\n{{/code}}\n")
        else:
            # Inline code
            self.output.write(f"###{text}###")

    def _handle_todo(self, element: etree._Element) -> None:
        """Handle Evernote todo checkboxes."""
        checked = element.get("checked", "false") == "true"

        if checked:
            self.output.write("[x] ")
        else:
            self.output.write("[ ] ")

    def _handle_encrypted(self, element: etree._Element) -> None:
        """Handle encrypted content placeholder."""
        self.output.write("\n{{warning}}\n")
        self.output.write("This content was encrypted in Evernote and cannot be converted.\n")
        self.output.write("{{/warning}}\n")

    def _get_element_text(self, element: etree._Element) -> str:
        """Get all text content from an element and its children."""
        texts = []
        if element.text:
            texts.append(unescape(element.text))

        for child in element:
            texts.append(self._get_element_text(child))
            if child.tail:
                texts.append(unescape(child.tail))

        return "".join(texts)

    def _strip_html(self, html: str) -> str:
        """Strip HTML tags as a fallback."""
        text = re.sub(r'<[^>]+>', '', html)
        return unescape(text)


def convert_note(note: Note, space: str = "ImportedNotes") -> ConvertedPage:
    """Convert an Evernote note to an XWiki page."""
    converter = ENMLToXWikiConverter(note, download_external_images=True)
    content = converter.convert()

    # Add metadata section at the end
    metadata_parts = []

    if note.created:
        metadata_parts.append(f"**Originally created:** {note.created.strftime('%Y-%m-%d %H:%M')}")

    if note.source_url:
        metadata_parts.append(f"**Source:** [[{note.source_url}]]")

    if metadata_parts:
        content += "\n\n----\n"
        content += "\n".join(metadata_parts)

    # Determine the space - always use the target space as the root
    if note.notebook:
        # Sanitize notebook name for use as subspace
        notebook_space = note.notebook.replace(" ", "").replace("/", ".").replace("\\", ".")
        page_space = f"{space}.{notebook_space}"
    else:
        page_space = space

    # Combine original attachments with downloaded images
    all_attachments = note.attachments.copy()
    all_attachments.extend(converter.downloaded_images)

    return ConvertedPage(
        title=note.title,
        content=content,
        space=page_space,
        tags=note.tags.copy(),
        attachments=all_attachments,
        created=note.created,
        updated=note.updated,
    )

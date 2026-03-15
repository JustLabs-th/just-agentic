"""scrape_page — fetch a URL and return clean text content for reports."""

import re
import urllib.parse

from langchain_core.tools import tool

from tools._safety import log_tool_call

_MAX_CHARS = 8_000
_TIMEOUT   = 15  # seconds

# Hosts that must never be reached (cloud metadata endpoints, etc.)
_BLOCKED_HOSTS: set[str] = {
    "169.254.169.254",   # AWS/GCP metadata
    "metadata.google.internal",
}


@tool
def scrape_page(url: str, css_selector: str = "") -> str:
    """Fetch a web page or internal URL and return its text content.

    Converts HTML to clean readable text. Useful for scraping internal dashboards,
    documentation sites, status pages, or JSON API endpoints to include in reports.

    JSON responses are returned as-is. HTML is stripped to plain text.
    Output is capped at 8 000 characters.

    Args:
        url:          HTTP or HTTPS URL to fetch.
        css_selector: Optional CSS selector to extract a specific section
                      (e.g. "main", "article", "#report-table").
                      Ignored for JSON responses.
    """
    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or "").lower()

    if hostname in _BLOCKED_HOSTS:
        out = f"BLOCKED: access to '{hostname}' is not permitted."
        log_tool_call("scrape_page", {"url": url}, out)
        return out

    if parsed.scheme not in ("http", "https"):
        out = "ERROR: Only http:// and https:// URLs are supported."
        log_tool_call("scrape_page", {"url": url}, out)
        return out

    try:
        import requests
    except ImportError:
        return "ERROR: 'requests' not installed. Run: pip install requests"

    try:
        resp = requests.get(
            url,
            timeout=_TIMEOUT,
            headers={"User-Agent": "just-agentic/1.0 (internal report scraper)"},
        )
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")

        if "application/json" in content_type:
            out = resp.text[:_MAX_CHARS]
            if len(resp.text) > _MAX_CHARS:
                out += f"\n\n_(truncated — {len(resp.text)} chars total)_"
        else:
            text = _html_to_text(resp.text, css_selector)
            out = text[:_MAX_CHARS]
            if len(text) > _MAX_CHARS:
                out += f"\n\n_(truncated — {len(text)} chars total)_"

        if not out.strip():
            out = "(page returned empty content)"

    except Exception as e:
        out = f"ERROR: {e}"

    log_tool_call("scrape_page", {"url": url, "css_selector": css_selector}, out)
    return out


def _html_to_text(html: str, css_selector: str = "") -> str:
    """Convert HTML to clean plain text. Uses BeautifulSoup when available."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "head", "nav", "footer", "noscript"]):
            tag.decompose()

        if css_selector:
            node = soup.select_one(css_selector)
            raw = node.get_text(separator="\n") if node else soup.get_text(separator="\n")
        else:
            raw = soup.get_text(separator="\n")

    except ImportError:
        # Fallback: regex-strip HTML tags
        raw = re.sub(r"<[^>]+>", " ", html)
        raw = re.sub(r"&[a-z]{2,6};", " ", raw)

    # Collapse blank lines and leading whitespace
    lines = [line.strip() for line in raw.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)

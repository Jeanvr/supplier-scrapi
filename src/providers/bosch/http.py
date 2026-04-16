from __future__ import annotations

from urllib.request import Request, urlopen

HTML_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


def fetch_url(url: str, headers: dict | None = None) -> tuple[str, str, str]:
    req = Request(url, headers=headers or HTML_HEADERS)
    with urlopen(req, timeout=45) as response:
        final_url = response.geturl()
        content_type = response.headers.get("Content-Type", "")
        html = response.read().decode("utf-8", errors="replace")
        return html, final_url, content_type
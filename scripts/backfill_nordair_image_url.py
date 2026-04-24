from __future__ import annotations

import argparse
import html
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


DEFAULT_CATALOG = Path("data/catalogs/nordair_catalog.jsonl")
DEFAULT_OUTPUT = Path("/tmp/nordair_catalog_with_images.jsonl")
SEARCH_BASE_URL = "https://comercio.nordair.es/buscar"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


def clean_spaces(value: object) -> str:
    return " ".join(str(value or "").split())


def code_from_pdf_url(pdf_url: str) -> str:
    query = parse_qs(urlparse(clean_spaces(pdf_url)).query)
    values = query.get("no_", [])
    return clean_spaces(values[0]) if values else ""


class ProductLinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._is_product_name = False
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        classes = clean_spaces(attrs_dict.get("class", "")).split()
        if tag.lower() == "a" and "product-name" in classes:
            self._href = urljoin(self.base_url, html.unescape(clean_spaces(attrs_dict.get("href", ""))))
            self._is_product_name = True
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._is_product_name:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._is_product_name:
            return

        text = clean_spaces(" ".join(self._text))
        if self._href and text:
            self.links.append((text, self._href))
        self._href = ""
        self._is_product_name = False
        self._text = []


class ImageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.images: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return

        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        for key in ("src", "data-src"):
            image_url = urljoin(self.base_url, html.unescape(clean_spaces(attrs_dict.get(key, ""))))
            if _is_large_default_image(image_url):
                self.images.append(image_url)


def _is_large_default_image(image_url: str) -> bool:
    image_url = clean_spaces(image_url)
    low = image_url.lower()
    if not low.startswith(("http://", "https://")):
        return False
    if "large_default" not in low:
        return False
    if any(token in low for token in ("logo", "icon", "favicon", "payment", "forma_pago")):
        return False
    return low.split("?", 1)[0].endswith((".jpg", ".jpeg", ".png", ".webp"))


def fetch_html(url: str, timeout: int) -> str:
    request = Request(url, headers=REQUEST_HEADERS)
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def find_product_url_for_code(code: str, timeout: int) -> str:
    query = urlencode({"controller": "search", "search_query": code})
    search_url = f"{SEARCH_BASE_URL}?{query}"

    try:
        html_text = fetch_html(search_url, timeout)
    except (HTTPError, URLError, TimeoutError, OSError):
        return ""

    parser = ProductLinkParser(search_url)
    parser.feed(html_text)

    for text, href in parser.links:
        if clean_spaces(text).casefold() == code.casefold():
            return href

    return ""


def extract_large_default_image(product_url: str, timeout: int) -> str:
    try:
        html_text = fetch_html(product_url, timeout)
    except (HTTPError, URLError, TimeoutError, OSError):
        return ""

    parser = ImageParser(product_url)
    parser.feed(html_text)
    return parser.images[0] if parser.images else ""


def load_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if clean_spaces(line):
            rows.append(json.loads(line))
    return rows


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    temp_path.replace(path)


def backfill(catalog_path: Path, output_path: Path, timeout: int) -> dict[str, int | str]:
    rows = load_rows(catalog_path)
    code_cache: dict[str, str] = {}
    exact_matches = 0
    rows_updated = 0

    codes = sorted(
        {
            code_from_pdf_url(clean_spaces(row.get("pdf_url", "")))
            for row in rows
            if code_from_pdf_url(clean_spaces(row.get("pdf_url", "")))
        }
    )

    for code in codes:
        product_url = find_product_url_for_code(code, timeout)
        if not product_url:
            code_cache[code] = ""
            continue

        exact_matches += 1
        code_cache[code] = extract_large_default_image(product_url, timeout)

    for row in rows:
        if clean_spaces(row.get("image_url", "")):
            continue

        code = code_from_pdf_url(clean_spaces(row.get("pdf_url", "")))
        image_url = code_cache.get(code, "")
        if image_url:
            row["image_url"] = image_url
            rows_updated += 1

    write_rows(output_path, rows)

    return {
        "total_rows": len(rows),
        "codes_found": len(codes),
        "exact_matches": exact_matches,
        "rows_updated": rows_updated,
        "image_url_empty": sum(1 for row in rows if not clean_spaces(row.get("image_url", ""))),
        "output": str(output_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill image_url for Nordair catalog rows.")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG), help="Nordair JSONL catalog path")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="Output JSONL path")
    parser.add_argument("--in-place", action="store_true", help="Overwrite the source catalog")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    catalog_path = Path(args.catalog)
    output_path = catalog_path if args.in_place else Path(args.out)

    summary = backfill(catalog_path, output_path, args.timeout)
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()

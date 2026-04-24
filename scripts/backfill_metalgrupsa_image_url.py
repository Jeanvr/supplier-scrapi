from __future__ import annotations

import argparse
import json
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


DEFAULT_CATALOG = Path("data/catalogs/metalgrupsa_catalog.jsonl")
DEFAULT_OUTPUT = Path("/tmp/metalgrupsa_catalog_with_images.jsonl")
PRODUCT_IMAGE_URL = "https://www.metalgrup.eu/sites/default/files/811A.jpg"
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


def normalize_text(value: object) -> str:
    text = unescape(clean_spaces(value)).casefold()
    for mark in ('"', "'", "\u201c", "\u201d", "\u2018", "\u2019", "\u2033"):
        text = text.replace(mark, "")
    return text


def _looks_like_target_product(text: str) -> bool:
    normalized = normalize_text(text)
    return "grifo lavadora" in normalized and "1/2" in normalized and "3/4" in normalized


class MetalgrupListingParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.cards: list[dict[str, list[str] | str]] = []
        self._card_depth = 0
        self._card_text: list[str] = []
        self._card_images: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        tag_low = tag.lower()

        if self._card_depth:
            self._card_depth += 1

        classes = clean_spaces(attrs_dict.get("class", "")).split()
        if tag_low == "div" and "thumbnail" in classes and not self._card_depth:
            self._card_depth = 1
            self._card_text = []
            self._card_images = []

        if self._card_depth and tag_low == "img":
            for key in ("src", "data-src"):
                src = clean_spaces(attrs_dict.get(key, ""))
                if src:
                    self._card_images.append(urljoin(self.base_url, src))

    def handle_data(self, data: str) -> None:
        if self._card_depth:
            text = clean_spaces(data)
            if text:
                self._card_text.append(text)

    def handle_endtag(self, tag: str) -> None:
        if not self._card_depth:
            return

        self._card_depth -= 1
        if self._card_depth == 0:
            self.cards.append(
                {
                    "text": clean_spaces(" ".join(self._card_text)),
                    "images": self._card_images[:],
                }
            )


def fetch_html(url: str, timeout: int) -> str:
    request = Request(url, headers=REQUEST_HEADERS)
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def source_has_target_card(source_url: str, timeout: int) -> bool:
    try:
        html = fetch_html(source_url, timeout)
    except (HTTPError, URLError, TimeoutError, OSError):
        return False

    parser = MetalgrupListingParser(source_url)
    parser.feed(html)

    for card in parser.cards:
        text = str(card.get("text", ""))
        images = card.get("images", [])
        if not _looks_like_target_product(text):
            continue
        if any(str(image).split("?", 1)[0].endswith("/811A.jpg") for image in images):
            return True

    return False


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
    source_cache: dict[str, bool] = {}
    rows_updated = 0

    for row in rows:
        if clean_spaces(row.get("image_url", "")):
            continue

        source_url = clean_spaces(row.get("source_url", ""))
        if not source_url:
            continue

        if source_url not in source_cache:
            source_cache[source_url] = source_has_target_card(source_url, timeout)

        if source_cache[source_url]:
            row["image_url"] = PRODUCT_IMAGE_URL
            rows_updated += 1

    write_rows(output_path, rows)

    return {
        "total_rows": len(rows),
        "source_urls": len({clean_spaces(row.get("source_url", "")) for row in rows if clean_spaces(row.get("source_url", ""))}),
        "target_cards_found": sum(1 for found in source_cache.values() if found),
        "rows_updated": rows_updated,
        "image_url_empty": sum(1 for row in rows if not clean_spaces(row.get("image_url", ""))),
        "output": str(output_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill image_url for Metalgrup catalog rows.")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG), help="Metalgrup JSONL catalog path")
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

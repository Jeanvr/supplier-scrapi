from __future__ import annotations

import argparse
import json
import re
import ssl
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


DEFAULT_CATALOG = Path("data/catalogs/aquaramvalvesfittingsslch_catalog.jsonl")
DEFAULT_OUTPUT = Path("/tmp/aquaramvalvesfittingsslch_catalog_with_images.jsonl")
GROUPS = (
    "bola_verde_socket",
    "bola_verde_rosca",
    "bola_roja_socket",
    "bola_roja_rosca",
    "retencion_y",
    "retencion_molla",
)
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
}


@dataclass
class Card:
    text: str
    href: str
    images: list[str]


def clean_spaces(value: object) -> str:
    return " ".join(str(value or "").split())


def normalize_text(value: object) -> str:
    text = unescape(clean_spaces(value)).casefold()
    for mark in ('"', "'", "\u201c", "\u201d", "\u2018", "\u2019", "\u2033"):
        text = text.replace(mark, " ")
    return clean_spaces(text)


def detect_group(row: dict) -> str:
    text = normalize_text(f"{row.get('name', '')} {row.get('search_text', '')}")

    if "retenci" in text and "molla" in text:
        return "retencion_molla"
    if "retenci" in text and " y " in f" {text} " and "bola" in text:
        return "retencion_y"
    if "maneta verda" in text:
        return "bola_verde_rosca" if "rosca" in text else "bola_verde_socket"
    if "maneta vermella" in text:
        return "bola_roja_rosca" if "rosca" in text else "bola_roja_socket"
    return ""


def preview_ref(row: dict) -> str:
    search_text = clean_spaces(row.get("search_text", ""))
    match = re.search(r"\bC-H[A-Z0-9]+\b", search_text)
    if match:
        return match.group(0)
    return clean_spaces(row.get("supplier_ref", ""))


def is_valid_aquaram_image(url: str) -> bool:
    url = clean_spaces(url)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.netloc not in {"www.aquaram.com", "aquaram.com"}:
        return False

    url_low = url.casefold()
    blocked = ("favicon", "icon-", "logo", "perception", ".svg")
    if any(token in url_low for token in blocked):
        return False

    return any(url_low.split("?", 1)[0].endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp"))


class AquaramCardParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.cards: list[Card] = []
        self._depth = 0
        self._href = ""
        self._text: list[str] = []
        self._images: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.casefold(): value or "" for key, value in attrs}
        tag = tag.casefold()

        if self._depth:
            self._depth += 1
        elif tag == "a" and clean_spaces(attrs_dict.get("href", "")):
            self._depth = 1
            self._href = urljoin(self.base_url, clean_spaces(attrs_dict.get("href", "")))
            self._text = []
            self._images = []

        if self._depth and tag == "img":
            for key in ("src", "data-src"):
                image_url = urljoin(self.base_url, clean_spaces(attrs_dict.get(key, "")))
                if is_valid_aquaram_image(image_url):
                    self._images.append(image_url)

    def handle_data(self, data: str) -> None:
        if self._depth:
            text = clean_spaces(data)
            if text:
                self._text.append(text)

    def handle_endtag(self, tag: str) -> None:
        if not self._depth:
            return

        self._depth -= 1
        if self._depth == 0:
            text = clean_spaces(" ".join(self._text))
            if self._href and text:
                self.cards.append(Card(text=text, href=self._href, images=self._images[:]))
            self._href = ""
            self._text = []
            self._images = []


def fetch_html(url: str, timeout: int) -> str:
    request = Request(url, headers=REQUEST_HEADERS)
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except URLError:
        context = ssl._create_unverified_context()
        with urlopen(request, timeout=timeout, context=context) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")


def parse_cards(html: str, base_url: str) -> list[Card]:
    parser = AquaramCardParser(base_url)
    parser.feed(html)
    return parser.cards


def find_card(cards: list[Card], title: str) -> Card | None:
    wanted = normalize_text(title)
    for card in cards:
        if normalize_text(card.text) == wanted and card.images:
            return card
    return None


def first_image(card: Card | None) -> str:
    if not card:
        return ""
    return card.images[0] if card.images else ""


def build_group_image_map(source_urls: list[str], timeout: int) -> dict[str, str]:
    image_by_group = {group: "" for group in GROUPS}

    for source_url in source_urls:
        try:
            html = fetch_html(source_url, timeout)
        except (HTTPError, URLError, TimeoutError, OSError):
            continue

        source_cards = parse_cards(html, source_url)
        check_y_card = find_card(source_cards, 'CHECK VALVE "Y"')
        if check_y_card:
            image_by_group["retencion_y"] = first_image(check_y_card)

        two_way_card = find_card(source_cards, "2 WAY BALL VALVE")
        if not two_way_card:
            continue

        try:
            two_way_html = fetch_html(two_way_card.href, timeout)
        except (HTTPError, URLError, TimeoutError, OSError):
            continue

        two_way_cards = parse_cards(two_way_html, two_way_card.href)
        socket_card = find_card(two_way_cards, "2 WAY BALL VALVE MODEL SOCKET EPDM")
        thread_card = find_card(two_way_cards, "2 WAY BALL VALVE MODEL THREAD EPDM")
        if socket_card:
            image_by_group["bola_verde_socket"] = first_image(socket_card)
        if thread_card:
            image_by_group["bola_verde_rosca"] = first_image(thread_card)

    return image_by_group


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


def print_preview(rows: list[dict], image_by_group: dict[str, str]) -> None:
    print("referencia | nombre | grupo_detectado | image_url")
    print("--- | --- | --- | ---")
    for row in rows:
        group = detect_group(row)
        image_url = image_by_group.get(group, "") if group else ""
        print(
            " | ".join(
                (
                    preview_ref(row),
                    clean_spaces(row.get("name", "")),
                    group,
                    image_url,
                )
            )
        )


def backfill(catalog_path: Path, output_path: Path, timeout: int) -> dict[str, int | str]:
    rows = load_rows(catalog_path)
    source_urls = sorted(
        {
            clean_spaces(row.get("source_url", ""))
            for row in rows
            if clean_spaces(row.get("source_url", ""))
        }
    )
    image_by_group = build_group_image_map(source_urls, timeout)
    rows_updated = 0

    print_preview(rows, image_by_group)

    for row in rows:
        if clean_spaces(row.get("image_url", "")):
            continue

        group = detect_group(row)
        image_url = image_by_group.get(group, "")
        if image_url:
            row["image_url"] = image_url
            rows_updated += 1

    write_rows(output_path, rows)

    return {
        "total_rows": len(rows),
        "source_urls": len(source_urls),
        "groups_detected": sum(1 for row in rows if detect_group(row)),
        "group_image_urls_found": sum(1 for value in image_by_group.values() if value),
        "rows_updated": rows_updated,
        "image_url_empty": sum(1 for row in rows if not clean_spaces(row.get("image_url", ""))),
        "output": str(output_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preview and backfill image_url for Aquaram catalog rows.")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG), help="Aquaram JSONL catalog path")
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

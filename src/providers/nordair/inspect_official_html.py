from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

import requests

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.text import clean_spaces


CATALOG_PATH = REPO_ROOT / "data/catalogs/nordair_catalog.jsonl"
BACKUP_PATH = REPO_ROOT / "data/catalogs/nordair_catalog.jsonl.bak_images"
SEARCH_URL_TEMPLATE = "https://comercio.nordair.es/buscar?s={query}"
TIMEOUT = 20
FALLBACK_IMAGE_EXTENSIONS = (".jpg", ".jpeg")
IMAGE_BLOCKLIST_HINTS = ("logo", "pago", "pattern")


class _SearchResultParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.product_links: list[str] = []
        self.family_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {key.lower(): value or "" for key, value in attrs}
        href = clean_spaces(unescape(attr_map.get("href", "")))
        if not href:
            return
        absolute = urljoin(self.base_url, href)
        path = (urlparse(absolute).path or "").lower()
        if path.endswith(".html"):
            if absolute not in self.product_links:
                self.product_links.append(absolute)
            return
        if re.search(r"/\d+-[a-z0-9-]+$", path) and absolute not in self.family_links:
            self.family_links.append(absolute)


class _ReferenceLinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.current_href = ""
        self.current_text: list[str] = []
        self.matches: list[tuple[str, str]] = []
        self.in_anchor = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {key.lower(): value or "" for key, value in attrs}
        href = clean_spaces(unescape(attr_map.get("href", "")))
        if not href:
            return
        self.in_anchor = True
        self.current_href = urljoin(self.base_url, href)
        self.current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self.in_anchor:
            return
        anchor_text = clean_spaces(unescape("".join(self.current_text)))
        self.matches.append((anchor_text, self.current_href))
        self.in_anchor = False
        self.current_href = ""
        self.current_text = []

    def handle_data(self, data: str) -> None:
        if self.in_anchor:
            self.current_text.append(data)


class _ProductImageMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta_images: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta":
            return
        attr_map = {key.lower(): value or "" for key, value in attrs}
        if clean_spaces(attr_map.get("itemprop", "")).lower() != "image":
            return
        content = clean_spaces(unescape(attr_map.get("content", "")))
        if content and content not in self.meta_images:
            self.meta_images.append(content)


class _ImageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.thickbox_default: list[str] = []
        self.large_default: list[str] = []
        self.fallback_jpgs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key.lower(): value or "" for key, value in attrs}
        values = [attr_map.get("src", ""), attr_map.get("data-src", ""), attr_map.get("href", "")]
        classes = clean_spaces(unescape(attr_map.get("class", ""))).lower()
        data_image_large = clean_spaces(unescape(attr_map.get("data-image-large-src", "")))

        if data_image_large:
            self._add_candidate(data_image_large, classes, preferred_size="")

        for value in values:
            self._add_candidate(value, classes)

    def _add_candidate(self, raw_value: str, classes: str, preferred_size: str | None = None) -> None:
        value = clean_spaces(unescape(raw_value))
        if not value:
            return
        absolute = urljoin(self.base_url, value)
        lower = absolute.lower()
        if "thickbox_default" in lower or preferred_size == "thickbox_default":
            self._append_unique(self.thickbox_default, absolute)
            return
        if "large_default" in lower or preferred_size == "large_default":
            self._append_unique(self.large_default, absolute)
            return
        if any(ext in lower for ext in FALLBACK_IMAGE_EXTENSIONS):
            if any(hint in lower for hint in IMAGE_BLOCKLIST_HINTS):
                return
            if "logo" in classes:
                return
            self._append_unique(self.fallback_jpgs, absolute)

    @staticmethod
    def _append_unique(bucket: list[str], value: str) -> None:
        if value not in bucket:
            bucket.append(value)


def _load_catalog_rows(catalog_path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in catalog_path.read_text(encoding="utf-8").splitlines():
        line = clean_spaces(line)
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _get_reference(row: dict) -> str:
    return clean_spaces(row.get("reference", "")) or clean_spaces(row.get("supplier_ref", ""))


def _family_prefix(reference: str) -> str:
    match = re.match(r"^([A-Za-z]{2}\d{2})", clean_spaces(reference))
    if not match:
        return ""
    return match.group(1).lower()


def _fetch(url: str) -> tuple[int | str, str]:
    response = requests.get(url, timeout=TIMEOUT)
    status_code = response.status_code
    response.raise_for_status()
    response.encoding = response.encoding or response.apparent_encoding or "utf-8"
    return status_code, response.text


def _find_product_page_url(reference: str) -> tuple[str, int | str]:
    search_url = SEARCH_URL_TEMPLATE.format(query=quote_plus(reference))
    status_code, html = _fetch(search_url)
    parser = _SearchResultParser(search_url)
    parser.feed(html)

    prefix = _family_prefix(reference)
    if prefix:
        prefix_fragment = f"/{prefix}/"
        for link in parser.product_links:
            if prefix_fragment in link.lower():
                return link, status_code
        for link in parser.family_links:
            if link.lower().endswith(prefix):
                family_status_code, family_html = _fetch(link)
                product_url = _find_reference_in_family_page(reference, link, family_html)
                if product_url:
                    return product_url, family_status_code

    return "", status_code


def _find_reference_in_family_page(reference: str, family_page_url: str, html: str) -> str:
    parser = _ReferenceLinkParser(family_page_url)
    parser.feed(html)
    target = clean_spaces(reference).upper()
    for anchor_text, href in parser.matches:
        if clean_spaces(anchor_text).upper() != target:
            continue
        if href.lower().endswith(".html"):
            return href
    return ""


def _select_image_url(product_page_url: str, html: str) -> str:
    parser = _ImageParser(product_page_url)
    parser.feed(html)
    meta_parser = _ProductImageMetaParser()
    meta_parser.feed(html)

    if parser.thickbox_default:
        return parser.thickbox_default[0]
    if parser.large_default:
        return parser.large_default[0]
    if parser.fallback_jpgs:
        return parser.fallback_jpgs[0]
    for meta_image in meta_parser.meta_images:
        lower = meta_image.lower()
        if any(hint in lower for hint in IMAGE_BLOCKLIST_HINTS):
            continue
        return meta_image
    return ""


def _resolve_row(row: dict) -> dict:
    reference = _get_reference(row)
    result = {
        "reference": reference,
        "product_page_url": "",
        "image_url": "",
        "status_code": "empty_reference" if not reference else "not_found",
    }

    if not reference:
        return result

    try:
        product_page_url, _ = _find_product_page_url(reference)
        if not product_page_url:
            return result

        status_code, product_html = _fetch(product_page_url)
        image_url = _select_image_url(product_page_url, product_html)
        result["product_page_url"] = product_page_url
        result["image_url"] = image_url
        result["status_code"] = str(status_code)
        return result
    except requests.RequestException as exc:
        result["status_code"] = f"error: {exc}"
        return result


def _print_result(result: dict) -> None:
    print(f"reference: {result['reference']}")
    print(f"product_page_url: {result['product_page_url']}")
    print(f"image_url: {result['image_url']}")
    print(f"status_code: {result['status_code']}")
    print()


def _write_catalog(rows: list[dict], catalog_path: Path) -> None:
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    catalog_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _update_catalog(rows: list[dict], results: list[dict], catalog_path: Path) -> None:
    shutil.copyfile(catalog_path, BACKUP_PATH)

    results_by_reference = {result["reference"]: result for result in results}
    updated_images = 0
    not_found = 0

    for row in rows:
        reference = _get_reference(row)
        result = results_by_reference.get(reference)
        if not result or not result.get("image_url"):
            not_found += 1
            continue
        row["image_url"] = result["image_url"]
        row["product_page_url"] = result["product_page_url"]
        row["pdf_url"] = ""
        updated_images += 1

    _write_catalog(rows, catalog_path)

    print("Resumen")
    print(f"  rows: {len(rows)}")
    print(f"  updated_images: {updated_images}")
    print(f"  not_found: {not_found}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Nordair official product HTML.")
    parser.add_argument(
        "--update-catalog",
        action="store_true",
        help="Update nordair_catalog.jsonl image_url and product_page_url for rows with resolved images.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    rows = _load_catalog_rows(CATALOG_PATH)
    results: list[dict] = []

    for row in rows:
        result = _resolve_row(row)
        results.append(result)
        _print_result(result)

    if args.update_catalog:
        _update_catalog(rows, results, CATALOG_PATH)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

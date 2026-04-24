from __future__ import annotations

import argparse
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_CATALOG = Path("data/catalogs/wattsindibericasa_catalog.jsonl")
DEFAULT_OUTPUT = Path("/tmp/wattsindibericasa_catalog_with_images.jsonl")
EXPECTED_REDUFIX_IMAGE_URL = "https://www.watts.eu/dfsmedia/0533dbba17714b1ab581ab07a4cbb521/637386-50060/638386907020000000"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
}


def clean_spaces(value: object) -> str:
    return " ".join(str(value or "").split())


def _srcset_urls(value: str) -> list[str]:
    urls: list[str] = []
    for part in value.split(","):
        url = clean_spaces(part).split(" ", 1)[0]
        if url:
            urls.append(url)
    return urls


def _is_valid_image_url(url: str) -> bool:
    url = clean_spaces(url)
    url_low = url.lower()

    if not url_low.startswith(("http://", "https://")):
        return False

    blocked_fragments = (
        "width=device-width",
        "/assets/",
        "/asset/",
        "/icon",
        "icon.",
        ".svg",
        ".css",
        ".js",
    )
    if any(fragment in url_low for fragment in blocked_fragments):
        return False

    image_markers = (".jpg", ".jpeg", ".png", ".webp", ".gif", "dfsmedia")
    if not any(marker in url_low for marker in image_markers):
        return False

    return True


def _looks_like_gallery_image(url: str, label: str) -> bool:
    if not _is_valid_image_url(url):
        return False

    url_low = clean_spaces(url).lower()
    text_low = f"{url} {label}".lower()

    blocked = (
        "close",
        "cookie",
        "facebook",
        "linkedin",
        "logo",
        "switch",
        "whatsapp",
        "youtube",
    )
    if any(token in url_low for token in blocked):
        return False

    return "redufix" in text_low or ("pressure" in text_low and "reducing" in text_low)


def _pick_best_image_url(candidates: list[str]) -> str:
    seen: set[str] = set()
    valid_candidates: list[str] = []

    for candidate in candidates:
        candidate = clean_spaces(candidate)
        if candidate in seen:
            continue
        seen.add(candidate)
        if _is_valid_image_url(candidate):
            valid_candidates.append(candidate)

    for candidate in valid_candidates:
        if candidate == EXPECTED_REDUFIX_IMAGE_URL:
            return candidate

    for candidate in valid_candidates:
        if "dfsmedia" in candidate.lower():
            return candidate

    return valid_candidates[0] if valid_candidates else ""


class WattsImageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.candidates: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() not in {"img", "source", "meta"}:
            return

        label = " ".join(
            clean_spaces(attrs_dict.get(key, ""))
            for key in ("alt", "title", "aria-label", "class", "id", "property", "name")
        )
        if tag.lower() == "meta" and "image" not in label.lower():
            return

        raw_urls: list[str] = []
        for key in ("src", "data-src", "data-lazy-src", "data-original", "content"):
            value = clean_spaces(attrs_dict.get(key, ""))
            if value:
                raw_urls.append(value)

        for key in ("srcset", "data-srcset"):
            value = clean_spaces(attrs_dict.get(key, ""))
            if value:
                raw_urls.extend(_srcset_urls(value))

        for raw_url in raw_urls:
            raw_url = clean_spaces(raw_url)
            if not raw_url.lower().startswith(("http://", "https://")):
                continue
            image_url = urljoin(self.base_url, raw_url)
            if _looks_like_gallery_image(image_url, label):
                self.candidates.append(image_url)


def fetch_html(url: str, timeout: int) -> str:
    request = Request(url, headers=REQUEST_HEADERS)
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def extract_watts_image_url(source_url: str, timeout: int) -> str:
    try:
        html = fetch_html(source_url, timeout)
    except (HTTPError, URLError, TimeoutError, OSError):
        html = ""

    if html:
        parser = WattsImageParser(source_url)
        parser.feed(html)

        image_url = _pick_best_image_url(parser.candidates)
        if image_url:
            return image_url

    return extract_watts_image_url_with_playwright(source_url, timeout)


def extract_watts_image_url_with_playwright(source_url: str, timeout: int) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=REQUEST_HEADERS["User-Agent"])
            page.goto(source_url, wait_until="networkidle", timeout=timeout * 1000)
            images = page.locator("img").evaluate_all(
                """elements => elements.map((img) => ({
                    src: img.currentSrc || img.src || "",
                    alt: img.alt || "",
                    title: img.title || "",
                    className: img.className || "",
                    id: img.id || ""
                }))"""
            )
        finally:
            browser.close()

    candidates: list[str] = []
    for image in images:
        image_url = clean_spaces(image.get("src", ""))
        label = " ".join(
            clean_spaces(image.get(key, ""))
            for key in ("alt", "title", "className", "id")
        )
        if _looks_like_gallery_image(image_url, label):
            candidates.append(image_url)

    return _pick_best_image_url(candidates)


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
    source_cache: dict[str, str] = {}
    rows_updated = 0

    for row in rows:
        if clean_spaces(row.get("image_url", "")):
            continue

        source_url = clean_spaces(row.get("source_url", ""))
        if not source_url:
            continue

        if source_url not in source_cache:
            source_cache[source_url] = extract_watts_image_url(source_url, timeout)

        image_url = source_cache[source_url]
        if image_url:
            row["image_url"] = image_url
            rows_updated += 1

    write_rows(output_path, rows)

    return {
        "total_rows": len(rows),
        "source_urls": len({clean_spaces(row.get("source_url", "")) for row in rows if clean_spaces(row.get("source_url", ""))}),
        "image_urls_found": sum(1 for value in source_cache.values() if value),
        "expected_image_url_rows": sum(1 for row in rows if clean_spaces(row.get("image_url", "")) == EXPECTED_REDUFIX_IMAGE_URL),
        "rows_updated": rows_updated,
        "output": str(output_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill image_url for Watts Iberica catalog rows.")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG), help="Watts JSONL catalog path")
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

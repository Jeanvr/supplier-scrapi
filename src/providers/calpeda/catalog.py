from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

BASE_URL = "https://www.calpeda.com"
PRODUCTS_URL = f"{BASE_URL}/en/products/"
REQUEST_TIMEOUT = 30
HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
TITLE_RE = re.compile(r"<title>\s*(.*?)\s*</title>", re.IGNORECASE | re.DOTALL)
OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
PDF_RE = re.compile(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', re.IGNORECASE)

def _fetch_text(url: str) -> str:
    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": "supplier-scrapi/1.0"},
    )
    response.raise_for_status()
    return response.text


def _unique(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in seq:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _extract_links(html: str, marker: str) -> list[str]:
    links: list[str] = []
    for raw_href in HREF_RE.findall(html):
        href = urljoin(BASE_URL, unescape(raw_href).strip())
        if marker not in href:
            continue
        if not href.startswith(BASE_URL):
            continue
        links.append(href)
    return _unique(links)

def _extract_title(html: str, fallback: str) -> str:
    match = TITLE_RE.search(html)
    if not match:
        return fallback

    title = unescape(match.group(1)).strip()
    title = re.sub(r"\s+", " ", title)
    title = re.sub(r"\s*-\s*Calpeda\s*$", "", title, flags=re.IGNORECASE)
    return title or fallback

def _extract_og_image(html: str) -> str:
    match = OG_IMAGE_RE.search(html)
    if not match:
        return ""
    return urljoin(BASE_URL, unescape(match.group(1)).strip())


def _extract_pdf_urls(html: str) -> list[str]:
    urls: list[str] = []
    for raw_href in PDF_RE.findall(html):
        href = urljoin(BASE_URL, unescape(raw_href).strip())
        if href.lower().endswith(".pdf") or ".pdf?" in href.lower():
            urls.append(href)
    return _unique(urls)
def _score_pdf_url(url: str) -> int:
    low = url.lower()
    score = 0

    if "/cataloghi_pdf/" in low:
        score += 20

    if "/datasheet_en/" in low:
        score += 120

    if "/en%20-%20english_new/" in low:
        score += 80
    elif "/en%20-%20english/" in low:
        score += 60

    if "60hz" in low or "/singoli_60hz/" in low:
        score -= 80

    if "/istruzioni" in low or "instruction" in low:
        score -= 140

    if "ie%20index" in low or "ie_index" in low or "/ie/" in low:
        score -= 120

    if "/it%20-%20italiano/" in low or "/it%20-%20italian/" in low:
        score -= 60

    return score

def _pick_pdf(pdf_urls: list[str]) -> str:
    if not pdf_urls:
        return ""

    return max(pdf_urls, key=_score_pdf_url)


def _slug_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    slug = path.split("/")[-1] if path else ""
    return slug.strip()


def load_catalog_rows(catalog_path: Path) -> list[dict]:
    if not catalog_path.exists():
        return []

    rows: list[dict] = []
    for line in catalog_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows
def _strip_html(html: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_search_text(product_html: str, title: str, supplier_ref: str) -> str:
    body_text = _strip_html(product_html)
    parts = [supplier_ref, title, body_text]
    return " ".join(part for part in parts if part).strip()

def build_catalog_jsonl(out_path: Path) -> int:
    products_html = _fetch_text(PRODUCTS_URL)
    range_urls = _extract_links(products_html, "/en/gamma/")
    print(f"calpeda_range_urls: {len(range_urls)}")

    rows: list[dict] = []
    seen_product_urls: set[str] = set()

    for range_url in range_urls:
        print(f"Scrapeando gama Calpeda: {range_url}")
        range_html = _fetch_text(range_url)
        product_urls = _extract_links(range_html, "/en/product/")

        for product_url in product_urls:
            if product_url in seen_product_urls:
                continue

            seen_product_urls.add(product_url)
            product_html = _fetch_text(product_url)

            slug = _slug_from_url(product_url)
            supplier_ref = slug.upper()
            title = _extract_title(product_html, fallback=supplier_ref)
            image_url = _extract_og_image(product_html)
            pdf_urls = _extract_pdf_urls(product_html)
            pdf_url = _pick_pdf(pdf_urls)
            search_text = _extract_search_text(product_html, title, supplier_ref)

            rows.append(
                {
    "brand": "calpeda",
    "supplier_ref": supplier_ref,
    "name": title,
    "source_url": product_url,
    "image_url": image_url,
    "pdf_url": pdf_url,
    "search_text": search_text,
}
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    return len(rows)
from __future__ import annotations

import argparse
import html
import re
from collections import OrderedDict
from urllib.parse import urljoin

import requests


VALVULERIA_URL = "https://www.heatsun.com/valvuleria/"
DEFAULT_CANDIDATES = [
    "https://www.heatsun.com/valvula-tve-160/",
    "https://www.heatsun.com/valvula-tvl-160/",
    "https://www.heatsun.com/valvula-tvb-250/",
    "https://www.heatsun.com/valvula-tvg-200/",
]
TIMEOUT = 20


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspección pequeña de URLs HEATSUN Valvuleria.")
    parser.add_argument("--discover", action="store_true", help="Descubre URLs valvula-* desde /valvuleria/")
    parser.add_argument("--url", action="append", default=[], help="URL extra a inspeccionar")
    return parser


def _dedupe(items: list[str]) -> list[str]:
    return list(OrderedDict.fromkeys(items))


def _clean(value: str) -> str:
    return " ".join(html.unescape(value).replace("\xa0", " ").split())


def _extract_first(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    return _clean(match.group(1)) if match else ""


def _extract_all(pattern: str, text: str, *, base_url: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
        url = urljoin(base_url, html.unescape(match.group(1)).strip())
        if url not in values:
            values.append(url)
    return values


def _looks_like_product_image(url: str) -> bool:
    lower = url.lower()
    if "logo" in lower:
        return False
    return lower.endswith((".jpg", ".jpeg", ".png", ".webp"))


def discover_candidate_urls() -> list[str]:
    response = requests.get(VALVULERIA_URL, timeout=TIMEOUT)
    response.raise_for_status()
    hrefs = _extract_all(r'href="([^"]+/valvula-[^"]+/)"', response.text, base_url=VALVULERIA_URL)
    return _dedupe(hrefs)


def inspect_url(url: str) -> dict:
    try:
        response = requests.get(url, timeout=TIMEOUT)
    except Exception as exc:
        return {"url": url, "status": "error", "error": str(exc)}

    info: dict = {"url": url, "status": response.status_code}
    if response.status_code != 200:
        return info

    text = response.text
    title = _extract_first(r"<title>(.*?)</title>", text) or _extract_first(
        r'property="og:title"\s+content="(.*?)"',
        text,
    )
    model = _extract_first(r"\b(V[ÁA]LVULA\s+[A-Z0-9 -]+)\b", title) or _extract_first(r"\b(TV[A-Z]-\d+)\b", title)
    pdfs = _extract_all(r'href="([^"]+\.pdf[^"]*)"', text, base_url=url)
    images = [
        image_url
        for image_url in _extract_all(r'(?:src|content)="([^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"', text, base_url=url)
        if _looks_like_product_image(image_url)
    ]

    info.update(
        {
            "title": title,
            "model": model,
            "pdfs": _dedupe(pdfs),
            "images": _dedupe(images),
        }
    )
    return info


def print_result(result: dict) -> None:
    print(f"URL: {result['url']}")
    print(f"status: {result['status']}")
    if result.get("error"):
        print(f"error: {result['error']}")
        print()
        return

    if result["status"] != 200:
        print("exists: no")
        print()
        return

    print("exists: yes")
    print(f"title: {result.get('title', '')}")
    print(f"model: {result.get('model', '')}")
    print("pdfs:")
    for pdf in result.get("pdfs", []):
        print(f"  - {pdf}")
    if not result.get("pdfs"):
        print("  -")
    print("images:")
    for image in result.get("images", []):
        print(f"  - {image}")
    if not result.get("images"):
        print("  -")
    print()


def main() -> None:
    args = build_parser().parse_args()

    urls = list(DEFAULT_CANDIDATES)
    if args.discover:
        urls.extend(discover_candidate_urls())
    urls.extend(args.url)
    urls = _dedupe(urls)

    print(f"valvuleria: {VALVULERIA_URL}")
    print(f"candidate_urls: {len(urls)}")
    print()
    for url in urls:
        print_result(inspect_url(url))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import re
import sys
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
import urllib3

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.text import clean_spaces


INPUT_EXCEL = "data/output/reports/teideindustrialsa_smoke_input.xlsx"
OUTPUT_EXCEL = "data/output/reports/teideindustrialsa_official_html_refs.xlsx"
START_URLS = [
    "https://www.teideindustrial.com/",
    "https://www.teideindustrial.com/esp/font.html",
    "https://www.teideindustrial.com/esp/tor_stand.html",
]
TIMEOUT = 20
PRIORITY_HINTS = (
    "font",
    "tor",
    "stand",
    "blister",
    "junta",
    "goma",
    "plac",
    "filtro",
    "malla",
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspección HTML oficial TEIDE Industrial.")
    parser.add_argument("--excel", default=INPUT_EXCEL, help="Excel smoke de entrada")
    parser.add_argument("--out", default=OUTPUT_EXCEL, help="Excel de salida con refs confirmadas")
    return parser


def _verify_for_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("teideindustrial.com"):
        return False
    return True


def _fetch_html(url: str) -> str:
    response = requests.get(url, timeout=TIMEOUT, verify=_verify_for_url(url))
    response.raise_for_status()
    response.encoding = response.encoding or "latin-1"
    return response.text


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", clean_spaces(unescape(value))).strip()


def _normalize_ref(value: str) -> str:
    return re.sub(r"\s+", "", clean_spaces(value).upper())


def _reference_variants(value: str) -> list[str]:
    base = _normalize_ref(value)
    if not base:
        return []

    variants = [base]
    normalized = (
        base.replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
        .replace("\\", "/")
    )
    if normalized not in variants:
        variants.append(normalized)

    if "/" in normalized:
        prefix = normalized.split("/", 1)[0]
        if prefix and prefix not in variants:
            variants.append(prefix)

    return list(dict.fromkeys(variants))


def _html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<script.*?>.*?</script>", " ", value)
    value = re.sub(r"(?is)<style.*?>.*?</style>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return _normalize_spaces(value)


def _is_relevant_teide_html_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if not host.endswith("teideindustrial.com"):
        return False
    if path == "/":
        return True
    return "/esp/" in path and path.endswith(".html")


def _url_priority(url: str) -> tuple[int, str]:
    lower = url.lower()
    hits = sum(1 for hint in PRIORITY_HINTS if hint in lower)
    return (-hits, lower)


def _discover_relevant_urls(base_url: str, html: str) -> list[str]:
    urls: list[str] = []

    for match in re.finditer(r'(?i)<frame[^>]+src=["\']([^"\']+)["\']', html):
        candidate = urljoin(base_url, match.group(1))
        if _is_relevant_teide_html_url(candidate) and candidate not in urls:
            urls.append(candidate)

    for match in re.finditer(r'(?i)href=["\']([^"\']+)["\']', html):
        candidate = urljoin(base_url, match.group(1))
        if _is_relevant_teide_html_url(candidate) and candidate not in urls:
            urls.append(candidate)

    return sorted(urls, key=_url_priority)


class _TableRowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_tr = False
        self.in_cell = False
        self.current_cell: list[str] = []
        self.current_row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.in_tr = True
            self.current_row = []
        elif tag in {"td", "th"} and self.in_tr:
            self.in_cell = True
            self.current_cell = []
        elif tag == "br" and self.in_cell:
            self.current_cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.in_tr and self.in_cell:
            self.in_cell = False
            self.current_row.append(_normalize_spaces("".join(self.current_cell)))
        elif tag == "tr" and self.in_tr:
            self.in_tr = False
            if any(clean_spaces(cell) for cell in self.current_row):
                self.rows.append(self.current_row)

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.current_cell.append(data)


def _extract_row_texts(url: str, html: str) -> tuple[list[str], bool]:
    row_texts: list[str] = []
    had_tables = False

    parser = _TableRowParser()
    parser.feed(html)
    if parser.rows:
        had_tables = True
    for row in parser.rows:
        row_text = _normalize_spaces(" | ".join(cell for cell in row if clean_spaces(cell)))
        if row_text:
            row_texts.append(row_text)

    if not row_texts:
        page_text = _html_to_text(html)
        if page_text:
            row_texts.append(page_text)

    return row_texts, had_tables


def collect_official_rows(start_urls: list[str]) -> list[dict]:
    queue = sorted(dict.fromkeys(start_urls), key=_url_priority)
    seen: set[str] = set()
    pages: list[dict] = []

    while queue:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)

        html = _fetch_html(url)
        row_texts, had_tables = _extract_row_texts(url, html)
        pages.append(
            {
                "url": url,
                "page_text": _html_to_text(html),
                "row_texts": row_texts,
                "had_tables": had_tables,
            }
        )

        for candidate in _discover_relevant_urls(url, html):
            if candidate not in seen and candidate not in queue:
                queue.append(candidate)
        queue.sort(key=_url_priority)

    return pages


def _find_best_match(reference: str, pages: list[dict]) -> dict:
    ref_variants = _reference_variants(reference)
    if not ref_variants:
        return {
            "official_page_url": "",
            "official_ref_found": "no",
            "official_row_text": "",
            "confidence": "none",
            "reason": "empty_reference",
        }

    for page in pages:
        for row_text in page["row_texts"]:
            normalized_row = _normalize_ref(row_text)
            for variant in ref_variants:
                if variant and variant in normalized_row:
                    reason = "exact_reference_in_html_table_row"
                    confidence = "high"
                    if variant != ref_variants[0]:
                        reason = "reference_variant_in_html_table_row"
                        confidence = "medium"
                    return {
                        "official_page_url": page["url"],
                        "official_ref_found": "yes",
                        "official_row_text": row_text,
                        "confidence": confidence,
                        "reason": reason,
                    }

    for page in pages:
        normalized_page = _normalize_ref(page["page_text"])
        for variant in ref_variants:
            if variant and variant in normalized_page:
                reason = "exact_reference_in_html_page"
                confidence = "medium"
                if variant != ref_variants[0]:
                    reason = "reference_variant_in_html_page"
                    confidence = "low"
                return {
                    "official_page_url": page["url"],
                    "official_ref_found": "yes",
                    "official_row_text": "",
                    "confidence": confidence,
                    "reason": reason,
                }

    return {
        "official_page_url": "",
        "official_ref_found": "no",
        "official_row_text": "",
        "confidence": "none",
        "reason": "reference_not_found_in_official_html",
    }


def build_report(input_excel: Path, output_excel: Path) -> tuple[pd.DataFrame, list[dict]]:
    df = pd.read_excel(input_excel, dtype=str).fillna("")
    pages = collect_official_rows(START_URLS)

    rows: list[dict] = []
    for _, row in df.iterrows():
        match = _find_best_match(clean_spaces(row.get("referencia", "")), pages)
        rows.append(
            {
                "codigo": clean_spaces(row.get("codigo", "")),
                "referencia": clean_spaces(row.get("referencia", "")),
                "nombre": clean_spaces(row.get("nombre", "")),
                "official_page_url": match["official_page_url"],
                "official_ref_found": match["official_ref_found"],
                "official_row_text": match["official_row_text"],
                "confidence": match["confidence"],
                "reason": match["reason"],
            }
        )

    report_df = pd.DataFrame(rows)
    output_excel.parent.mkdir(parents=True, exist_ok=True)
    report_df.to_excel(output_excel, index=False)
    return report_df, pages


def _missing_pattern(reference: str) -> str:
    ref = _normalize_ref(reference)
    if not ref:
        return "empty"
    if "/" in ref:
        return "contains_slash"
    if ref.count("-") >= 1 and "." in ref:
        return "dot_dash_combo"
    if ref.endswith("EXP"):
        return "assorted_exp"
    if re.fullmatch(r"\d+[A-Z]", ref):
        return "numeric_suffix_letter"
    return "other"


def main() -> None:
    args = build_parser().parse_args()
    report_df, pages = build_report(Path(args.excel), Path(args.out))
    page_counts = (
        report_df[report_df["official_ref_found"] == "yes"]["official_page_url"]
        .value_counts()
        .head(10)
    )
    pending_refs = report_df[report_df["official_ref_found"] == "no"]["referencia"].map(_missing_pattern).value_counts()
    pages_with_tables = sum(1 for page in pages if page.get("had_tables"))
    matched_pages = report_df[report_df["official_ref_found"] == "yes"]["official_page_url"].nunique()

    print(f"input_rows: {len(report_df)}")
    print(f"official_ref_found_yes: {int((report_df['official_ref_found'] == 'yes').sum())}")
    print(f"official_ref_found_no: {int((report_df['official_ref_found'] == 'no').sum())}")
    print(f"pages_visited: {len(pages)}")
    print(f"pages_with_tables: {pages_with_tables}")
    print(f"pages_with_pending_ref_hits: {matched_pages}")
    print("top_pages:")
    if page_counts.empty:
        print("  -")
    else:
        for page_url, count in page_counts.items():
            print(f"  {count} | {page_url}")
    print("missing_ref_patterns:")
    if pending_refs.empty:
        print("  -")
    else:
        for pattern, count in pending_refs.items():
            print(f"  {count} | {pattern}")
    print(f"output: {args.out}")


if __name__ == "__main__":
    main()

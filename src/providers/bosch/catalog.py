from __future__ import annotations

import ast
import json
from difflib import SequenceMatcher
from pathlib import Path

from src.core.text import (
    build_name_tokens,
    clean_spaces,
    normalize_search_text,
    normalize_text,
)


def first_non_empty(row: dict, keys: list[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue

        if isinstance(value, list):
            for item in value:
                item = clean_spaces(item)
                if item:
                    return item
            continue

        text = clean_spaces(value)
        if not text:
            continue

        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, list):
                    for item in parsed:
                        item = clean_spaces(item)
                        if item:
                            return item
            except Exception:
                pass

        return text

    return ""


def load_catalog_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []

    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            title = first_non_empty(
                row,
                ["nombre", "name", "title", "product_name", "product_title", "display_name"],
            )
            reference = first_non_empty(
                row,
                ["referencia", "reference", "order_number", "supplier_ref", "artpro", "codart"],
            )
            page_url = first_non_empty(
                row,
                ["product_url", "detail_url", "source_url", "url", "docs_url"],
            )
            docs_url = first_non_empty(
                row,
                ["docs_url"],
            )
            image_url = first_non_empty(
                row,
                ["image_url", "primary_image_url", "local_image", "images", "image_urls"],
            )
            pdf_url = first_non_empty(
                row,
                ["pdf_url", "tech_pdf_url", "file_urls"],
            )

            row["_title"] = title
            row["_reference"] = reference
            row["_page_url"] = page_url
            row["_docs_url"] = docs_url
            row["_image_url"] = image_url
            row["_pdf_url"] = pdf_url
            row["_search_blob"] = normalize_search_text(
                f"{title} {reference} {page_url} {docs_url}"
            )

            rows.append(row)

    return rows


def score_catalog_row(reference: str, name: str, row: dict) -> int:
    ref_norm = normalize_text(reference)
    name_norm = normalize_search_text(name)
    row_title = normalize_search_text(row.get("_title", ""))
    row_ref = normalize_text(row.get("_reference", ""))
    row_blob = row.get("_search_blob", "")

    score = 0

    if ref_norm and row_ref and ref_norm == row_ref:
        score += 3000

    if ref_norm and ref_norm in row_blob:
        score += 900

    query_tokens = set(build_name_tokens(name))
    row_tokens = set(build_name_tokens(row.get("_title", "")))
    score += len(query_tokens & row_tokens) * 90

    if name_norm and row_title:
        ratio = SequenceMatcher(None, name_norm, row_title).ratio()
        score += int(ratio * 400)

    for token in ["therm", "tronic", "6600", "2000", "sr", "vertical"]:
        if token in name_norm and token in row_title:
            score += 60

    if row.get("_page_url"):
        score += 20
    if row.get("_image_url"):
        score += 20
    if row.get("_pdf_url"):
        score += 10

    return score


def find_best_catalog_row(reference: str, name: str, catalog_rows: list[dict]) -> tuple[dict | None, int]:
    best_row = None
    best_score = -1

    for row in catalog_rows:
        score = score_catalog_row(reference, name, row)
        if score > best_score:
            best_score = score
            best_row = row

    if best_row is None:
        return None, -1

    if best_score < 220:
        return None, best_score

    return best_row, best_score
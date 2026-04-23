from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path

from src.core.text import clean_spaces


VALID_PDF_KINDS = {"ficha_tecnica", "catalogo_producto"}
FICHA_DOC_TYPES = {
    "ficha_tecnica",
    "datasheet",
    "data_booklet",
    "catalogo_tecnico",
    "fichaproducto_pdf",
    "product_sheet_pdf",
}
DEFAULT_STOPWORDS = {
    "SA",
    "S",
    "A",
    "SL",
    "REF",
    "CATALOGO",
    "CATÁLOGO",
}


def classify_document_kind(row: dict) -> str:
    explicit_kind = clean_spaces(row.get("pdf_kind", "")).lower()
    if explicit_kind in VALID_PDF_KINDS:
        return explicit_kind

    doc_type = clean_spaces(row.get("pdf_doc_type", "")).lower()
    if doc_type in FICHA_DOC_TYPES:
        return "ficha_tecnica"
    if clean_spaces(row.get("pdf_url", "")):
        return "catalogo_producto"
    return ""


def normalize_catalog_row(row: dict, *, default_brand: str) -> dict:
    normalized_row = dict(row)
    normalized_row["brand"] = clean_spaces(normalized_row.get("brand", "")) or default_brand
    normalized_row["supplier_ref"] = clean_spaces(normalized_row.get("supplier_ref", ""))
    normalized_row["name"] = clean_spaces(normalized_row.get("name", ""))
    normalized_row["source_url"] = clean_spaces(normalized_row.get("source_url", ""))
    normalized_row["image_url"] = clean_spaces(normalized_row.get("image_url", ""))
    normalized_row["pdf_url"] = clean_spaces(normalized_row.get("pdf_url", ""))
    normalized_row["pdf_title"] = clean_spaces(normalized_row.get("pdf_title", ""))
    normalized_row["pdf_language"] = clean_spaces(normalized_row.get("pdf_language", ""))
    normalized_row["pdf_doc_type"] = clean_spaces(normalized_row.get("pdf_doc_type", ""))
    normalized_row["search_text"] = clean_spaces(normalized_row.get("search_text", ""))
    normalized_row["pdf_kind"] = classify_document_kind(normalized_row)
    return normalized_row


def load_catalog_rows_for_brand(catalog_path: Path, *, default_brand: str) -> list[dict]:
    if not catalog_path.exists():
        return []

    rows: list[dict] = []
    for line in catalog_path.read_text(encoding="utf-8").splitlines():
        line = clean_spaces(line)
        if not line:
            continue
        rows.append(normalize_catalog_row(json.loads(line), default_brand=default_brand))

    return rows


def _normalize(text: str) -> str:
    text = clean_spaces(text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _compact(text: str) -> str:
    return _normalize(text).replace(" ", "")


def _tokens(text: str, *, stopwords: set[str]) -> list[str]:
    result: list[str] = []
    for token in _normalize(text).split():
        if token in stopwords:
            continue
        if token.endswith("S") and len(token) > 4:
            token = token[:-1]
        if len(token) >= 3 or any(ch.isdigit() for ch in token):
            result.append(token)
    return result


def _build_result(reference: str, name: str, *, status: str, notes: str) -> dict:
    return {
        "resolver_status": status,
        "reference": clean_spaces(reference),
        "name": clean_spaces(name),
        "matched_catalog_name": "",
        "matched_catalog_ref": "",
        "matched_catalog_score": "",
        "product_page_url": "",
        "product_page_title": "",
        "resolved_image_url": "",
        "preferred_pdf_kind": "",
        "preferred_pdf_label": "",
        "preferred_pdf_url": "",
        "preferred_pdf_check_ok": "",
        "preferred_pdf_content_type": "",
        "preferred_doc_type": "",
        "preferred_title": "",
        "fallback_doc_type": "",
        "fallback_title": "",
        "fallback_pdf_url": "",
        "notes": notes,
    }


def _build_not_found(reference: str, name: str, note: str) -> dict:
    return _build_result(reference, name, status="not_found", notes=note)


def _search_blob(row: dict) -> str:
    return _normalize(
        " ".join(
            part
            for part in [
                clean_spaces(row.get("supplier_ref", "")),
                clean_spaces(row.get("name", "")),
                clean_spaces(row.get("search_text", "")),
            ]
            if part
        )
    )


def make_resolver(
    provider_key: str,
    *,
    extra_stopwords: set[str] | None = None,
    min_score: int = 160,
) -> Callable[[str, str, list[dict]], dict]:
    stopwords = DEFAULT_STOPWORDS | {provider_key.upper()} | (extra_stopwords or set())

    def _score_row(reference: str, name: str, row: dict) -> int:
        score = 0
        ref_norm = _normalize(reference)
        ref_compact = _compact(reference)
        row_ref = clean_spaces(row.get("supplier_ref", ""))
        row_ref_norm = _normalize(row_ref)
        row_ref_compact = _compact(row_ref)
        name_norm = _normalize(name)
        name_compact = _compact(name)
        row_name = clean_spaces(row.get("name", ""))
        row_name_norm = _normalize(row_name)
        row_name_compact = _compact(row_name)

        if ref_norm and row_ref_norm and ref_norm == row_ref_norm:
            score += 100
        if ref_compact and row_ref_compact and ref_compact == row_ref_compact:
            score += 80

        if name_norm and row_name_norm and name_norm == row_name_norm:
            score += 500
        if name_compact and row_name_compact:
            if name_compact == row_name_compact:
                score += 450
            elif row_name_compact in name_compact or name_compact in row_name_compact:
                score += 180

        query_tokens = set(_tokens(f"{reference} {name}", stopwords=stopwords))
        row_tokens = set(_tokens(_search_blob(row), stopwords=stopwords))
        score += len(query_tokens & row_tokens) * 25

        if row.get("pdf_url"):
            score += 20
        if row.get("image_url"):
            score += 10

        return score

    def resolve_reference(reference: str, name: str, catalog_rows: list[dict]) -> dict:
        reference_clean = clean_spaces(reference)
        name_clean = clean_spaces(name)

        if not catalog_rows:
            return _build_not_found(reference_clean, name_clean, f"{provider_key}_catalog_empty")

        ranked_rows = sorted(
            ((_score_row(reference_clean, name_clean, row), row) for row in catalog_rows),
            key=lambda item: item[0],
            reverse=True,
        )
        best_score, best_row = ranked_rows[0] if ranked_rows else (-1, None)
        if best_row is None or best_score < min_score:
            return _build_not_found(reference_clean, name_clean, f"{provider_key}_no_catalog_match")

        matched_name = clean_spaces(best_row.get("name", ""))
        matched_ref = clean_spaces(best_row.get("supplier_ref", ""))
        image_url = clean_spaces(best_row.get("image_url", ""))
        pdf_url = clean_spaces(best_row.get("pdf_url", ""))
        pdf_kind = classify_document_kind(best_row)
        pdf_title = clean_spaces(best_row.get("pdf_title", "")) or matched_name
        pdf_doc_type = clean_spaces(best_row.get("pdf_doc_type", "")) or pdf_kind

        resolver_status = "not_found"
        if pdf_kind == "ficha_tecnica" and pdf_url:
            resolver_status = "resolved_ficha_tecnica"
        elif pdf_kind == "catalogo_producto" and pdf_url:
            resolver_status = "resolved_catalogo_producto"
        elif image_url:
            resolver_status = "resolved_image_only"

        return {
            "resolver_status": resolver_status,
            "reference": reference_clean,
            "name": name_clean,
            "matched_catalog_name": matched_name,
            "matched_catalog_ref": matched_ref,
            "matched_catalog_score": str(best_score),
            "product_page_url": clean_spaces(best_row.get("source_url", "")),
            "product_page_title": matched_name,
            "resolved_image_url": image_url,
            "preferred_pdf_kind": pdf_kind,
            "preferred_pdf_label": pdf_title if pdf_url else "",
            "preferred_pdf_url": pdf_url,
            "preferred_pdf_check_ok": "",
            "preferred_pdf_content_type": "",
            "preferred_doc_type": pdf_doc_type,
            "preferred_title": pdf_title if pdf_url else "",
            "fallback_doc_type": "",
            "fallback_title": "",
            "fallback_pdf_url": "",
            "notes": f"{provider_key}_catalog_match",
        }

    return resolve_reference

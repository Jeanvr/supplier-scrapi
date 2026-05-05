from __future__ import annotations

import re
import unicodedata

from src.core.text import clean_spaces
from src.providers.acfix.catalog import classify_document_kind


REFERENCE_PATTERNS = [
    r"\b[A-Z]\.[A-Z0-9]{2,4}\.[A-Z0-9]{1,8}(?:\.[A-Z0-9]{1,5})?L?\b",
    r"(?<![A-Z0-9.])\d{3}\.[A-Z0-9]{3,8}(?:\.[A-Z0-9]{1,5})?[A-Z]?\b",
    r"\bACF-\d{4,6}\b",
    r"\bL\d{2}\.\d{2}\.\d{2,4}\b",
    r"\bI\.0?\d{2}-[A-Z]\b",
]
REFERENCE_RE = re.compile("|".join(f"(?:{pattern})" for pattern in REFERENCE_PATTERNS), re.IGNORECASE)
REFERENCE_ALIASES = {
    "75404005": "075.404005",
    "75636005": "075.636005",
    "75162020": "075.162020",
    "I04925P": "I.049.25",
}


def _normalize(text: str) -> str:
    text = clean_spaces(text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _compact(text: str) -> str:
    return _normalize(text).replace(" ", "")


def _candidate_reference_keys(reference: str) -> list[str]:
    candidates = [_compact(reference)]
    for match in REFERENCE_RE.finditer(clean_spaces(reference).upper()):
        candidates.append(_compact(match.group(0)))
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


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
        "image_suspect": "",
        "image_review_reason": "",
        "image_match_scope": "",
        "catalog_page": "",
        "notes": notes,
    }


def _build_not_found(reference: str, name: str) -> dict:
    return _build_result(reference, name, status="not_found", notes="acfix_no_match")


def _rows_by_compact_ref(catalog_rows: list[dict]) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for row in catalog_rows:
        ref_key = _compact(clean_spaces(row.get("supplier_ref", "")))
        if ref_key:
            rows.setdefault(ref_key, row)
    return rows


def _find_catalog_row(reference: str, catalog_rows: list[dict]) -> tuple[dict | None, str]:
    rows_by_ref = _rows_by_compact_ref(catalog_rows)
    for ref_key in _candidate_reference_keys(reference):
        row = rows_by_ref.get(ref_key)
        if row is not None:
            return row, ""

        alias_ref = REFERENCE_ALIASES.get(ref_key, "")
        if alias_ref:
            row = rows_by_ref.get(_compact(alias_ref))
            if row is not None:
                return row, alias_ref

    return None, ""


def resolve_reference(reference: str, name: str, catalog_rows: list[dict]) -> dict:
    reference = clean_spaces(reference)
    name = clean_spaces(name)

    if not catalog_rows:
        return _build_result(reference, name, status="not_found", notes="acfix_catalog_empty")

    best_row, alias_ref = _find_catalog_row(reference, catalog_rows)
    if best_row is None:
        return _build_not_found(reference, name)

    matched_name = clean_spaces(best_row.get("name", ""))
    matched_ref = clean_spaces(best_row.get("supplier_ref", ""))
    pdf_url = clean_spaces(best_row.get("pdf_url", ""))
    pdf_kind = classify_document_kind(best_row)
    pdf_title = clean_spaces(best_row.get("pdf_title", "")) or matched_name

    resolver_status = "resolved_catalogo_producto" if pdf_kind == "catalogo_producto" and pdf_url else "not_found"

    notes = ["acfix_pdf_exact_ref", clean_spaces(best_row.get("catalog_notes", ""))]
    if alias_ref:
        notes.append(f"acfix_ref_alias:{reference}->{matched_ref}")

    return {
        "resolver_status": resolver_status,
        "reference": reference,
        "name": name,
        "matched_catalog_name": matched_name,
        "matched_catalog_ref": matched_ref,
        "matched_catalog_score": "1000",
        "product_page_url": clean_spaces(best_row.get("source_url", "")),
        "product_page_title": matched_name,
        "resolved_image_url": "",
        "preferred_pdf_kind": pdf_kind,
        "preferred_pdf_label": pdf_title if pdf_url else "",
        "preferred_pdf_url": pdf_url,
        "preferred_pdf_check_ok": "",
        "preferred_pdf_content_type": "",
        "preferred_doc_type": clean_spaces(best_row.get("pdf_doc_type", "")) or pdf_kind,
        "preferred_title": pdf_title if pdf_url else "",
        "fallback_doc_type": "",
        "fallback_title": "",
        "fallback_pdf_url": "",
        "image_suspect": "",
        "image_review_reason": "",
        "image_match_scope": "",
        "catalog_page": clean_spaces(best_row.get("catalog_page", "")),
        "notes": " | ".join(note for note in notes if note),
    }


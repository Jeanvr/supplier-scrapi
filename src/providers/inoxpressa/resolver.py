from __future__ import annotations

import re
import unicodedata

from src.core.text import clean_spaces
from src.providers.inoxpressa.catalog import classify_document_kind


STOPWORDS = {
    "INOXPRES",
    "INOXPRESSA",
    "SA",
    "S",
    "A",
    "REF",
    "CATALOGO",
    "CATÁLOGO",
}

PLACEHOLDER_REFS = {"01 20199"}

CATALOG_FALLBACK_URL = "https://inoxpres.com/wp-content/uploads/2023/01/CATALOGO_GENERAL_V2022_HD.pdf"

OFFICIAL_FAMILY_REVIEW_REASON = "official Inoxpres family/product image; verify variant visually"

OFFICIAL_IMAGE_BY_FAMILY = {}


def _normalize(text: str) -> str:
    text = clean_spaces(text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    text = re.sub(r"(\d)\s*/\s*(\d)", r"\1FR\2", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _compact(text: str) -> str:
    return _normalize(text).replace(" ", "")


def _tokens(text: str) -> list[str]:
    result: list[str] = []
    for token in _normalize(text).split():
        if token in STOPWORDS:
            continue
        if token.endswith("S") and len(token) > 4:
            token = token[:-1]
        if len(token) >= 3 or any(ch.isdigit() for ch in token):
            result.append(token)
    return result


def _digit_tokens(text: str) -> set[str]:
    return {token for token in _tokens(text) if any(ch.isdigit() for ch in token)}


def _row_value(row: dict | None, aliases: list[str]) -> str:
    if not row:
        return ""

    normalized = {clean_spaces(str(key)).casefold(): key for key in row}
    for alias in aliases:
        key = normalized.get(clean_spaces(alias).casefold())
        if key is not None:
            return clean_spaces(row.get(key, ""))

    return ""


def _provider_reference(reference: str, input_row: dict | None) -> str:
    return _row_value(input_row, ["Referencia prov", "referencia prov", "referencia"]) or clean_spaces(reference)


def _is_placeholder_ref(value: str) -> bool:
    return _normalize(value) in {_normalize(ref) for ref in PLACEHOLDER_REFS}


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
        "download_reference": "",
        "image_suspect": "",
        "image_review_reason": "",
        "image_match_scope": "",
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


def _has_strong_name_match(query_name: str, row_name: str) -> bool:
    query_norm = _normalize(query_name)
    row_norm = _normalize(row_name)
    if not query_norm or not row_norm:
        return False
    if query_norm == row_norm or _compact(query_name) == _compact(row_name):
        return True

    query_tokens = set(_tokens(query_name))
    row_tokens = set(_tokens(row_name))
    if not query_tokens or not row_tokens:
        return False

    overlap = query_tokens & row_tokens
    if len(overlap) < 3:
        return False

    coverage = len(overlap) / max(len(query_tokens), len(row_tokens))
    if coverage < 0.75:
        return False

    query_digits = _digit_tokens(query_name)
    row_digits = _digit_tokens(row_name)
    if query_digits and row_digits and query_digits != row_digits:
        return False

    return True


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

    query_tokens = set(_tokens(f"{reference} {name}"))
    row_tokens = set(_tokens(_search_blob(row)))
    score += len(query_tokens & row_tokens) * 25

    if _has_strong_name_match(name, row_name):
        score += 120

    if row.get("pdf_url"):
        score += 20

    return score


def _family_key(provider_ref: str, name: str) -> str:
    ref = _compact(provider_ref)
    text = _normalize(f"{provider_ref} {name}")

    if ref.startswith("20EPDM") or "JUNTA TORICA EPDM" in text:
        return "epdm"
    if ref.startswith("62V2CQ") or "VALVULA BOLA TOTAL 2P" in text or "Q2" in text:
        return "ball_valve"
    if ref.startswith("664VR") or "VALVULA RETENCIO" in text or "RETENCION" in text:
        return "check_valve"

    return ""


def _row_for_family(family: str, catalog_rows: list[dict]) -> dict | None:
    if not family:
        return None

    rows = list(catalog_rows)

    def find_by_text(*needles: str) -> dict | None:
        for row in rows:
            blob = _search_blob(row)
            if all(_normalize(needle) in blob for needle in needles):
                return row
        return None

    if family == "epdm":
        return find_by_text("JUNTA", "EPDM") or rows[0]
    if family in {"ball_valve", "check_valve"}:
        return (
            find_by_text("VALVULA", "BOLA")
            or find_by_text("VALVULA")
            or rows[0]
        )

    return None


def _catalog_result(
    *,
    reference: str,
    provider_ref: str,
    name: str,
    row: dict,
    score: int,
    family: str,
    notes: list[str],
) -> dict:
    matched_name = clean_spaces(row.get("name", "")) or name
    matched_ref = clean_spaces(row.get("supplier_ref", ""))

    if _is_placeholder_ref(matched_ref) and provider_ref:
        matched_ref = provider_ref
        notes.append("matched_ref_from_input_referencia_prov")

    pdf_url = clean_spaces(row.get("pdf_url", "")) or CATALOG_FALLBACK_URL
    pdf_kind = classify_document_kind(row) or "catalogo_producto"
    if pdf_url == CATALOG_FALLBACK_URL:
        pdf_kind = "catalogo_producto"

    pdf_title = clean_spaces(row.get("pdf_title", "")) or "Catalogo general Inoxpres"
    pdf_doc_type = clean_spaces(row.get("pdf_doc_type", "")) or "catalogo_web_pdf"

    # Inoxpres: do not use web/family images as final product images.
    # Product IMG will be generated later from the trimmed PDF page when a clean crop is available.
    image_url = ""
    image_suspect = ""
    image_review_reason = ""
    image_match_scope = ""
    
    return {
        "resolver_status": "resolved_catalogo_producto" if pdf_url else "not_found",
        "reference": reference,
        "name": name,
        "matched_catalog_name": matched_name,
        "matched_catalog_ref": matched_ref,
        "matched_catalog_score": str(score),
        "product_page_url": clean_spaces(row.get("source_url", "")),
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
        "download_reference": provider_ref,
        "image_suspect": image_suspect,
        "image_review_reason": image_review_reason,
        "image_match_scope": image_match_scope,
        "notes": " | ".join(notes),
    }


def resolve_reference(reference: str, name: str, catalog_rows: list[dict], input_row: dict | None = None) -> dict:
    reference = clean_spaces(reference)
    name = clean_spaces(name)
    provider_ref = _provider_reference(reference, input_row)

    if not catalog_rows:
        return _build_not_found(reference, name, "inoxpressa_catalog_empty")

    ranked_rows = sorted(
        ((_score_row(provider_ref, name, row), row) for row in catalog_rows),
        key=lambda item: item[0],
        reverse=True,
    )
    best_score, best_row = ranked_rows[0] if ranked_rows else (-1, None)

    notes = ["inoxpressa_catalog_match"]

    family = _family_key(provider_ref, name)
    family_row = _row_for_family(family, catalog_rows)

    if best_row is None or best_score < 260:
        if family_row is None:
            return _build_not_found(reference, name, "inoxpressa_no_catalog_match")
        best_row = family_row
        best_score = max(best_score, 260)
        notes.append(f"catalog_fallback_by_family:{family}")

    ref_compact = _compact(provider_ref)
    exact_ref_matches = [
        row for row in catalog_rows if ref_compact and _compact(clean_spaces(row.get("supplier_ref", ""))) == ref_compact
    ]
    matched_name = clean_spaces(best_row.get("name", ""))
    if len(exact_ref_matches) > 1 and not _has_strong_name_match(name, matched_name):
        return _build_not_found(reference, name, "inoxpressa_ambiguous_reference_requires_name")

    return _catalog_result(
        reference=reference,
        provider_ref=provider_ref,
        name=name,
        row=best_row,
        score=best_score,
        family=family,
        notes=notes,
    )

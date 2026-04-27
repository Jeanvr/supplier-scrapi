from __future__ import annotations

import re
import unicodedata

from src.core.text import clean_spaces
from src.providers.genebresa.catalog import classify_document_kind


STOPWORDS = {
    "GENEBRE",
    "GENEBRESA",
    "GE",
    "SA",
    "S",
    "A",
    "REF",
    "CATALOGO",
    "CATÁLOGO",
}

GENERIC_COVER_IMAGE_MARKERS = (
    "/media/contents/download/portada_",
)


def _append_note(notes: str, note: str) -> str:
    notes = clean_spaces(notes)
    if not notes:
        return note
    if note in notes:
        return notes
    return f"{notes} | {note}"


def _is_generic_catalog_cover_image(image_url: str) -> bool:
    image_url = clean_spaces(image_url).casefold()
    return any(marker in image_url for marker in GENERIC_COVER_IMAGE_MARKERS)


def _normalize(text: str) -> str:
    text = clean_spaces(text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
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


def _reference_base(reference: str) -> str:
    return _normalize(reference).split()[0] if _normalize(reference) else ""


def _official_pdf_url(reference: str) -> str:
    base = _reference_base(reference)
    if not base:
        return ""
    return f"https://pim.genebre.es/genebre/documents/fichas_tecnicas/{base}.pdf"


def _official_image_url(reference: str) -> str:
    base = _reference_base(reference)
    if not base:
        return ""
    image_base = "2108A" if base == "2108AB" else base
    return f"https://www.genebre.es/media/contents/product/mh/{image_base}.jpg"


def _is_placeholder_ref(value: str) -> bool:
    return _compact(value) == "0120492"


def _can_derive_exact_ref(reference: str, name: str, row: dict) -> bool:
    base = _reference_base(reference)
    if not base:
        return False

    row_blob = _search_blob(row)
    row_blob_compact = row_blob.replace(" ", "")
    numeric_family = re.match(r"\d+", base)
    family_match = base in row_blob_compact or bool(numeric_family and numeric_family.group(0) in row_blob_compact)
    if not family_match:
        return False

    name_norm = _normalize(name)
    row_name_norm = _normalize(clean_spaces(row.get("name", "")))
    return bool(name_norm and row_name_norm and (name_norm == row_name_norm or row_name_norm in name_norm))


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

    if row.get("pdf_url"):
        score += 20
    if row.get("image_url"):
        score += 10

    return score


def resolve_reference(reference: str, name: str, catalog_rows: list[dict]) -> dict:
    reference = clean_spaces(reference)
    name = clean_spaces(name)

    if not catalog_rows:
        return _build_not_found(reference, name, "genebresa_catalog_empty")

    ranked_rows = sorted(
        ((_score_row(reference, name, row), row) for row in catalog_rows),
        key=lambda item: item[0],
        reverse=True,
    )
    best_score, best_row = ranked_rows[0] if ranked_rows else (-1, None)
    if best_row is None or best_score < 160:
        return _build_not_found(reference, name, "genebresa_no_catalog_match")

    matched_name = clean_spaces(best_row.get("name", ""))
    matched_ref = clean_spaces(best_row.get("supplier_ref", ""))
    raw_image_url = clean_spaces(best_row.get("image_url", ""))
    image_url = raw_image_url
    notes = "genebresa_catalog_match"
    if _is_generic_catalog_cover_image(raw_image_url):
        image_url = ""
        notes = _append_note(notes, "image:suppressed_generic_catalog_cover")
    pdf_url = clean_spaces(best_row.get("pdf_url", ""))
    pdf_kind = classify_document_kind(best_row)
    pdf_title = clean_spaces(best_row.get("pdf_title", "")) or matched_name
    pdf_doc_type = clean_spaces(best_row.get("pdf_doc_type", "")) or pdf_kind
    image_match_scope = clean_spaces(best_row.get("image_match_scope", ""))
    notes = ["genebresa_catalog_match"]

    if _is_placeholder_ref(matched_ref) and _can_derive_exact_ref(reference, name, best_row):
        matched_ref = reference
        image_url = _official_image_url(reference)
        pdf_url = _official_pdf_url(reference)
        pdf_kind = "ficha_tecnica"
        pdf_title = f"Ficha tecnica Genebre {clean_spaces(_reference_base(reference))}"
        pdf_doc_type = "ficha_tecnica"
        image_match_scope = "official_family_image"
        notes.append("derived_exact_ref_from_input")
        notes.append("official_family_datasheet_pdf")
        notes.append(f"image_scope:{image_match_scope}")
        notes.append("image_review:official_family_image_verify_size_variant")
        if _reference_base(reference) == "2108AB":
            notes.append("image_base:2108A_for_2108AB")

    resolver_status = "not_found"
    if pdf_kind == "ficha_tecnica" and pdf_url:
        resolver_status = "resolved_ficha_tecnica"
    elif pdf_kind == "catalogo_producto" and pdf_url:
        resolver_status = "resolved_catalogo_producto"
    elif image_url:
        resolver_status = "resolved_image_only"

    return {
        "resolver_status": resolver_status,
        "reference": reference,
        "name": name,
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
        "image_suspect": "review" if image_match_scope == "official_family_image" else "",
        "image_review_reason": "official family image; verify size/variant visually" if image_match_scope == "official_family_image" else "",
        "image_match_scope": image_match_scope,
        "notes": " | ".join(notes),
    }

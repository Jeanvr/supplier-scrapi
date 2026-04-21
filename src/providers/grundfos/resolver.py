from __future__ import annotations

import re
import unicodedata

from src.core.text import clean_spaces


STOPWORDS = {
    "GRUNDFOS",
    "BOMBA",
    "BOMBAS",
    "GRUP",
    "PRESSIO",
    "PRESSURE",
    "MANAGER",
    "AUTO",
    "AUTOMATIC",
    "CENTRIFUGA",
    "CENTRIFUGAL",
    "WITH",
    "WITHOUT",
    "AND",
    "THE",
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


def _tokens(text: str) -> list[str]:
    result: list[str] = []
    for token in _normalize(text).split():
        if token in STOPWORDS:
            continue
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


def _build_skipped_non_grundfos(reference: str, name: str) -> dict:
    return _build_result(
        reference,
        name,
        status="skipped_non_grundfos_row",
        notes="grundfos_skipped_non_grundfos_row:name_without_grundfos",
    )


def _looks_like_grundfos_row(reference: str, name: str, catalog_rows: list[dict]) -> bool:
    name_norm = _normalize(name)
    if "GRUNDFOS" in name_norm:
        return True

    if name_norm:
        return False

    ref_norm = _normalize(reference)
    ref_compact = _compact(reference)
    for row in catalog_rows:
        row_ref = clean_spaces(row.get("supplier_ref", ""))
        if not row_ref:
            continue
        if ref_norm and ref_norm == _normalize(row_ref):
            return True
        if ref_compact and ref_compact == _compact(row_ref):
            return True

    return False


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
    name_compact = _compact(name)
    row_name = clean_spaces(row.get("name", ""))
    row_name_compact = _compact(row_name)

    if ref_norm and row_ref_norm and ref_norm == row_ref_norm:
        score += 400
    if ref_compact and row_ref_compact and ref_compact == row_ref_compact:
        score += 350

    query_tokens = set(_tokens(f"{reference} {name}"))
    row_tokens = set(_tokens(_search_blob(row)))
    score += len(query_tokens & row_tokens) * 20

    if row_name_compact and len(row_name_compact) >= 4 and row_name_compact in name_compact:
        score += 80
    if row.get("pdf_url"):
        score += 3
    if row.get("image_url"):
        score += 1

    return score


def _classify_pdf_kind(row: dict) -> str:
    explicit_kind = clean_spaces(row.get("pdf_kind", "")).lower()
    if explicit_kind in {"ficha_tecnica", "catalogo_producto"}:
        return explicit_kind

    pdf_url = clean_spaces(row.get("pdf_url", ""))
    low = pdf_url.lower()
    if not low:
        return ""

    if any(marker in low for marker in ("catalog", "catalogue", "brochure")):
        return "catalogo_producto"

    if "api.grundfos.com/literature/" in low:
        return "ficha_tecnica"

    if any(marker in low for marker in ("datasheet", "data-booklet", "databooklet", "technical")):
        return "ficha_tecnica"

    return ""


def resolve_reference(reference: str, name: str, catalog_rows: list[dict]) -> dict:
    reference = clean_spaces(reference)
    name = clean_spaces(name)

    if not _looks_like_grundfos_row(reference, name, catalog_rows):
        return _build_skipped_non_grundfos(reference, name)

    if not catalog_rows:
        return _build_not_found(reference, name, "grundfos_catalog_empty")

    ranked_rows = sorted(
        ((_score_row(reference, name, row), row) for row in catalog_rows),
        key=lambda item: item[0],
        reverse=True,
    )
    best_score, best_row = ranked_rows[0] if ranked_rows else (-1, None)
    if best_row is None or best_score < 80:
        return _build_not_found(reference, name, "grundfos_no_catalog_match")

    matched_name = clean_spaces(best_row.get("name", ""))
    matched_ref = clean_spaces(best_row.get("supplier_ref", ""))
    image_url = clean_spaces(best_row.get("image_url", ""))
    pdf_url = clean_spaces(best_row.get("pdf_url", ""))
    pdf_kind = _classify_pdf_kind(best_row)

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
        "preferred_pdf_label": matched_name if pdf_url else "",
        "preferred_pdf_url": pdf_url,
        "preferred_pdf_check_ok": "",
        "preferred_pdf_content_type": "",
        "preferred_doc_type": pdf_kind,
        "preferred_title": matched_name if pdf_url else "",
        "fallback_doc_type": "",
        "fallback_title": "",
        "fallback_pdf_url": "",
        "notes": "grundfos_catalog_match",
    }

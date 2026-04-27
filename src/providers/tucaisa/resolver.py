from __future__ import annotations

import re
import unicodedata

from src.core.text import clean_spaces
from src.providers.tucaisa.catalog import classify_document_kind


STOPWORDS = {
    "TUCAI",
    "SA",
    "S",
    "A",
    "TMM",
    "TAQ",
    "REF",
    "CATALOGO",
    "CATÁLOGO",
}

PLACEHOLDER_REFS = {"01 20863"}

OFFICIAL_FAMILY_REVIEW_REASON = "official Tucai family/product image; verify variant visually"

OFFICIAL_PAGE_BY_FAMILY = {
    "TAQ_PREMIUM": "https://www.tucai.com/producto/taq-premium/",
    "C850_PREMIUM": "https://www.tucai.com/producto/c850-premium/",
    "L400": "https://www.tucai.com/producto/tmm-l-400/",
    "M550": "https://www.tucai.com/producto/m550/",
    "C400": "https://www.tucai.com/producto/c400/",
    "C502": "https://www.tucai.com/producto/c502/",
    "C511": "https://www.tucai.com/producto/c511/",
    "C340": "https://www.tucai.com/producto/c340/",
}

OFFICIAL_FAMILY_IMAGE_BY_FAMILY = {
    "TAQ_PREMIUM": "https://www.tucai.com/wp-content/uploads/2024/04/DSC01067-1.jpg",
    "C850_PREMIUM": "https://www.tucai.com/wp-content/uploads/2024/04/Gama-Premium-Valves.jpg",
    "L400": "https://www.tucai.com/wp-content/uploads/2023/06/L400-simple-sin-floron.jpg",
    "M550": "https://www.tucai.com/wp-content/uploads/2023/06/M550.jpg",
    "C400": "https://www.tucai.com/wp-content/uploads/2023/06/GC-C400-ER-12x34-1-scaled.jpg",
    "C501_C502": "https://www.tucai.com/wp-content/uploads/2023/06/C501-C502.jpg",
    "C511": "https://www.tucai.com/wp-content/uploads/2024/04/C511-white-red.jpg",
    "C340": "https://www.tucai.com/wp-content/uploads/2023/06/C-340.jpg",
}

OFFICIAL_SKU_IMAGE_BY_REFERENCE = {
    "918500301": "https://www.tucai.com/wp-content/uploads/2024/04/Chrome-C850-Premium.jpg",
    "918500302": "https://www.tucai.com/wp-content/uploads/2024/04/White-C850-Premium.jpg",
    "918500303": "https://www.tucai.com/wp-content/uploads/2024/04/Black-matte-C850-Premium.jpg",
    "918500305": "https://www.tucai.com/wp-content/uploads/2024/04/Antique-Bronze-C850-Premium.jpg",
    "918500306": "https://www.tucai.com/wp-content/uploads/2024/04/Steel-C850-Premium.jpg",
    "918500307": "https://www.tucai.com/wp-content/uploads/2024/04/Gold-C850-Premium.jpg",
    "918500308": "https://www.tucai.com/wp-content/uploads/2024/04/Rose-Gold-C850-Premium.jpg",
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
        "download_reference": "",
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


def _is_placeholder_ref(value: str) -> bool:
    return _normalize(value) in {_normalize(ref) for ref in PLACEHOLDER_REFS}


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
    return _row_value(input_row, ["Referencia prov", "referencia prov", "referencia"]) or reference


def _official_image_match(provider_reference: str, name: str, best_row: dict) -> dict:
    reference_key = _compact(provider_reference)
    name_norm = _normalize(f"{name} {best_row.get('name', '')}")
    source_url = clean_spaces(best_row.get("source_url", ""))

    if reference_key in OFFICIAL_SKU_IMAGE_BY_REFERENCE:
        return {
            "url": OFFICIAL_SKU_IMAGE_BY_REFERENCE[reference_key],
            "scope": "sku",
            "page": OFFICIAL_PAGE_BY_FAMILY["C850_PREMIUM"],
            "suspect": "",
            "review_reason": "",
            "note": "official_sku_image",
        }

    family = ""
    if "taq-premium" in source_url or "TAQ PREMIUM" in name_norm or "TAQPREMIUM" in _compact(name_norm):
        family = "TAQ_PREMIUM"
    elif "c850-premium" in source_url or "C 850" in name_norm or "C850" in name_norm:
        family = "C850_PREMIUM"
    elif "tmm-l-400" in source_url or "L 400" in name_norm or "L400" in name_norm:
        family = "L400"
    elif reference_key in {"0208104", "0208105", "0208106"}:
        family = "M550"
    elif "C 400" in name_norm or "C400" in name_norm:
        family = "C400"
    elif "C 501" in name_norm or "C501" in name_norm or "C 502" in name_norm or "C502" in name_norm:
        family = "C501_C502"
    elif "C 511" in name_norm or "C511" in name_norm:
        family = "C511"
    elif "C 340" in name_norm or "C340" in name_norm:
        family = "C340"

    if not family:
        return {}

    page_key = "C502" if family == "C501_C502" else family
    return {
        "url": OFFICIAL_FAMILY_IMAGE_BY_FAMILY[family],
        "scope": "official_family_image",
        "page": OFFICIAL_PAGE_BY_FAMILY.get(page_key, source_url),
        "suspect": "review",
        "review_reason": OFFICIAL_FAMILY_REVIEW_REASON,
        "note": f"official_family_image:{family.lower()}",
    }


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


def resolve_reference(reference: str, name: str, catalog_rows: list[dict], input_row: dict | None = None) -> dict:
    reference = clean_spaces(reference)
    name = clean_spaces(name)
    provider_reference = _provider_reference(reference, input_row)

    if not catalog_rows:
        return _build_not_found(reference, name, "tucaisa_catalog_empty")

    ranked_rows = sorted(
        ((_score_row(provider_reference, name, row), row) for row in catalog_rows),
        key=lambda item: item[0],
        reverse=True,
    )
    best_score, best_row = ranked_rows[0] if ranked_rows else (-1, None)
    if best_row is None or best_score < 160:
        return _build_not_found(reference, name, "tucaisa_no_catalog_match")

    matched_name = clean_spaces(best_row.get("name", ""))
    matched_ref = clean_spaces(best_row.get("supplier_ref", ""))
    image_url = clean_spaces(best_row.get("image_url", ""))
    pdf_url = clean_spaces(best_row.get("pdf_url", ""))
    pdf_kind = classify_document_kind(best_row)
    pdf_title = clean_spaces(best_row.get("pdf_title", "")) or matched_name
    pdf_doc_type = clean_spaces(best_row.get("pdf_doc_type", "")) or pdf_kind
    product_page_url = clean_spaces(best_row.get("source_url", ""))
    image_suspect = ""
    image_review_reason = ""
    image_match_scope = ""
    notes = ["tucaisa_catalog_match"]

    if _is_placeholder_ref(matched_ref):
        if provider_reference:
            matched_ref = provider_reference
            notes.append("matched_ref_from_input_referencia_prov")

    if not image_url:
        official_image = _official_image_match(provider_reference, name, best_row)
        if official_image:
            image_url = official_image["url"]
            image_match_scope = official_image["scope"]
            image_suspect = official_image["suspect"]
            image_review_reason = official_image["review_reason"]
            product_page_url = official_image["page"]
            notes.append(official_image["note"])
            if image_suspect:
                notes.append(f"image_review:{image_review_reason}")

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
        "download_reference": provider_reference,
        "product_page_url": product_page_url,
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
        "image_suspect": image_suspect,
        "image_review_reason": image_review_reason,
        "image_match_scope": image_match_scope,
        "notes": " | ".join(notes),
    }

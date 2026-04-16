from __future__ import annotations

from src.core.text import clean_spaces
from src.providers.bosch.catalog import find_best_catalog_row
from src.providers.bosch.config import DOCS_SEARCH_URL
from src.providers.bosch.docs_portal import resolve_from_docs_portal
from src.providers.bosch.http import HTML_HEADERS, fetch_url
from src.providers.bosch.media import validate_pdf_url
from src.providers.bosch.product_page import resolve_from_product_page


def resolve_reference(reference: str, name: str, catalog_rows: list[dict]) -> dict:
    matched_row, matched_score = find_best_catalog_row(reference, name, catalog_rows)

    product_page_url = ""
    product_page_title = ""
    matched_catalog_name = ""
    matched_catalog_ref = ""
    matched_catalog_score = matched_score if matched_row else ""
    resolved_image_url = ""
    preferred_pdf_kind = ""
    preferred_pdf_label = ""
    preferred_pdf_url = ""
    notes: list[str] = []

    if matched_row is not None:
        matched_catalog_name = clean_spaces(matched_row.get("_title", ""))
        matched_catalog_ref = clean_spaces(matched_row.get("_reference", ""))
        candidate_page_url = clean_spaces(matched_row.get("_page_url", ""))
        candidate_image_url = clean_spaces(matched_row.get("_image_url", ""))

        if candidate_page_url:
            page_result = resolve_from_product_page(
                candidate_page_url,
                candidate_image_url,
                fetch_html=fetch_url,
                html_headers=HTML_HEADERS,
            )
            product_page_url = page_result.get("product_page_url", "")
            product_page_title = page_result.get("product_page_title", "")
            resolved_image_url = page_result.get("resolved_image_url", "")
            preferred_pdf_kind = page_result.get("preferred_pdf_kind", "")
            preferred_pdf_label = page_result.get("preferred_pdf_label", "")
            preferred_pdf_url = page_result.get("preferred_pdf_url", "")
            if page_result.get("page_notes"):
                notes.append(page_result["page_notes"])
        else:
            resolved_image_url = candidate_image_url
            notes.append("catalog_match_sin_page_url")
    else:
        notes.append("sin_match_fuerte_en_bosch_catalog")

    docs_fallback = resolve_from_docs_portal(
        reference,
        name,
        search_url_template=DOCS_SEARCH_URL,
        fetch_html=fetch_url,
        html_headers=HTML_HEADERS,
    )
    if not preferred_pdf_url and docs_fallback.get("fallback_pdf_url"):
        preferred_pdf_kind = clean_spaces(docs_fallback.get("fallback_doc_type", ""))
        preferred_pdf_label = clean_spaces(docs_fallback.get("fallback_title", ""))
        preferred_pdf_url = clean_spaces(docs_fallback.get("fallback_pdf_url", ""))
        notes.append("pdf_resuelto_desde_docs_portal")

    pdf_check_ok = ""
    pdf_content_type = ""
    if preferred_pdf_url:
        ok, final_pdf_url, content_type = validate_pdf_url(preferred_pdf_url)
        preferred_pdf_url = final_pdf_url
        pdf_check_ok = ok
        pdf_content_type = content_type

    status = "not_found"
    if preferred_pdf_kind == "ficha_tecnica" and preferred_pdf_url:
        status = "resolved_ficha_tecnica"
    elif preferred_pdf_kind == "catalogo_producto" and preferred_pdf_url:
        status = "resolved_catalogo_producto"
    elif resolved_image_url:
        status = "resolved_image_only"

    return {
        "resolver_status": status,
        "reference": reference,
        "name": name,
        "matched_catalog_name": matched_catalog_name,
        "matched_catalog_ref": matched_catalog_ref,
        "matched_catalog_score": matched_catalog_score,
        "product_page_url": product_page_url,
        "product_page_title": product_page_title,
        "resolved_image_url": resolved_image_url,
        "preferred_pdf_kind": preferred_pdf_kind,
        "preferred_pdf_label": preferred_pdf_label,
        "preferred_pdf_url": preferred_pdf_url,
        "preferred_pdf_check_ok": pdf_check_ok,
        "preferred_pdf_content_type": pdf_content_type,
        "preferred_doc_type": preferred_pdf_kind,
        "preferred_title": preferred_pdf_label,
        "fallback_doc_type": docs_fallback.get("fallback_doc_type", ""),
        "fallback_title": docs_fallback.get("fallback_title", ""),
        "fallback_pdf_url": docs_fallback.get("fallback_pdf_url", ""),
        "notes": " | ".join([n for n in notes if n]),
    }
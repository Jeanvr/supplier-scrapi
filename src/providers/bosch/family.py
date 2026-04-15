from __future__ import annotations

import re

from src.core.text import clean_spaces


def bosch_family_key(name: str) -> str:
    raw = clean_spaces(name).upper()
    if not raw:
        return ""

    raw = re.sub(r"\b(BOSCH|JUNKERS)\b", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()

    model_match = re.search(r"\b([A-Z]{1,8}\d{3,4}[A-Z]{0,3})\b", raw)
    model = model_match.group(1) if model_match else ""

    orientation = ""
    if "VERTICAL" in raw:
        orientation = "VERTICAL"
    elif "HORIZONTAL" in raw:
        orientation = "HORIZONTAL"

    cleaned = re.sub(r"\b\d{2,4}\s*[A-Z]\b", " ", raw)
    cleaned = re.sub(r"\b\d{2,4}\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    parts = []
    if model:
        parts.append(model)
    if orientation:
        parts.append(orientation)
    if cleaned:
        parts.append(cleaned)

    return " | ".join(parts)


def promote_family_tech_sheets(results: list[dict]) -> list[dict]:
    family_tech_map: dict[str, dict] = {}

    for result in results:
        if result.get("resolver_status") != "resolved_ficha_tecnica":
            continue

        family_key = bosch_family_key(
            result.get("name", "") or result.get("matched_catalog_name", "")
        )
        pdf_url = clean_spaces(result.get("preferred_pdf_url", ""))

        if not family_key or not pdf_url:
            continue

        if family_key not in family_tech_map:
            family_tech_map[family_key] = {
                "preferred_pdf_url": pdf_url,
                "preferred_pdf_kind": "ficha_tecnica",
                "preferred_pdf_label": clean_spaces(result.get("preferred_pdf_label", "")),
                "preferred_pdf_check_ok": result.get("preferred_pdf_check_ok", ""),
                "preferred_pdf_content_type": result.get("preferred_pdf_content_type", ""),
                "source_reference": result.get("reference", ""),
            }

    for result in results:
        if result.get("resolver_status") != "resolved_catalogo_producto":
            continue

        family_key = bosch_family_key(
            result.get("name", "") or result.get("matched_catalog_name", "")
        )
        inherited = family_tech_map.get(family_key)

        if not inherited:
            continue

        result["preferred_pdf_url"] = inherited["preferred_pdf_url"]
        result["preferred_pdf_kind"] = "ficha_tecnica"
        result["preferred_doc_type"] = "ficha_tecnica"
        result["preferred_pdf_label"] = inherited["preferred_pdf_label"] or result.get("preferred_pdf_label", "")
        result["preferred_title"] = result["preferred_pdf_label"]
        result["preferred_pdf_check_ok"] = inherited["preferred_pdf_check_ok"]
        result["preferred_pdf_content_type"] = inherited["preferred_pdf_content_type"]
        result["resolver_status"] = "resolved_ficha_tecnica"

        inherited_note = f"family_tech_inherited_from:{inherited['source_reference']}"
        existing_notes = clean_spaces(result.get("notes", ""))
        result["notes"] = " | ".join([x for x in [existing_notes, inherited_note] if x])

    return results
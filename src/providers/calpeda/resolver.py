from __future__ import annotations

import re
import unicodedata

from src.core.text import clean_spaces
from src.providers.bosch.media import attach_downloads


STOPWORDS = {
    "CALPEDA",
    "BOMBA",
    "BOMBES",
    "SUBM",
    "SUBMERGIBLE",
    "SUBMERGIBLES",
    "SUBMERSIBLE",
    "MOTOR",
    "MOTORS",
    "GRUP",
    "PRESSIO",
    "PRESSION",
    "REGULADOR",
    "INTERRUPTOR",
    "NIVELL",
    "NIVEL",
    "CABLE",
    "ARMARI",
    "ELECTRIC",
    "ELECTRICA",
    "ELECTRICO",
    "AIGUA",
    "BRUTA",
    "NETA",
    "TRIF",
    "MONOF",
    "SENSE",
    "AMB",
    "VARIADOR",
    "INTEGRAT",
    "ESTACIO",
    "BOMBEIG",
    "CV",
    "CON",
    "SIN",
    "WITH",
    "WITHOUT",
    "AND",
    "THE",
}


def _fix_mojibake(text: str) -> str:
    text = clean_spaces(text)
    if not text:
        return ""
    if "Ã" in text or "Â" in text:
        try:
            return text.encode("latin-1").decode("utf-8")
        except Exception:
            return text
    return text


def _normalize(text: str) -> str:
    text = _fix_mojibake(text)
    text = clean_spaces(text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _compact(text: str) -> str:
    return _normalize(text).replace(" ", "")


def _tokens(text: str) -> list[str]:
    out = []
    for token in _normalize(text).split():
        if token in STOPWORDS:
            continue
        if len(token) >= 3 or any(ch.isdigit() for ch in token):
            out.append(token)
    return out


def _query_hints(reference: str, name: str) -> str:
    raw = f"{reference} {name}"
    norm = _normalize(raw)
    compact = norm.replace(" ", "")

    hints: list[str] = []

    if "META" in norm or "MÈTA" in _fix_mojibake(raw).upper():
        hints.append("META")

    if "MXPM" in compact or re.search(r"\bMXP\b", norm):
        hints.extend(["MXP", "E MXP"])

    if re.search(r"\bNM\b", norm) or re.search(r"\bNMD\b", norm):
        hints.extend(["NM", "NMD"])

    if "V75K" in compact or "V 75K" in norm:
        hints.extend(["V", "V75K", "V 75K"])

    if "V100K" in compact or "V 100K" in norm:
        hints.extend(["V", "V100K", "V 100K"])

    if "4CSR" in compact or "4CS R" in norm:
        hints.extend(["4CSR", "4CS R", "4CS"])

    if "4FK" in compact or "FRANKLIN" in norm:
        hints.extend(["4FK", "FRANKLIN"])

    if "PMAT" in norm:
        hints.append("PMAT")

    if "AKO" in norm:
        hints.append("AKO")

    return " ".join(hints)


def _search_blob(row: dict) -> str:
    parts = [
        row.get("supplier_ref", ""),
        row.get("name", ""),
        row.get("search_text", ""),
    ]
    return _normalize(" ".join(str(part) for part in parts if part))

def _score_row(reference: str, name: str, row: dict) -> int:
    score = 0

    query_hints = _query_hints(reference, name)
    query_text = f"{reference} {name} {query_hints}".strip()

    name_norm = _normalize(query_text)
    name_compact = _compact(query_text)
    ref_norm = _normalize(reference)
    ref_compact = _compact(reference)

    blob = _search_blob(row)
    blob_compact = blob.replace(" ", "")

    row_name = _normalize(row.get("name", ""))
    row_ref = _normalize(row.get("supplier_ref", ""))

    name_tokens = set(_tokens(query_text))
    blob_tokens = set(_tokens(blob))
    overlap = name_tokens & blob_tokens

    score += len(overlap) * 18

    if row_name and f" {row_name} " in f" {name_norm} ":
        score += 140

    row_name_compact = row_name.replace(" ", "")
    if row_name_compact and len(row_name_compact) >= 3 and row_name_compact in name_compact:
        score += 120

    if row_ref and f" {row_ref} " in f" {name_norm} ":
        score += 110

    row_ref_compact = row_ref.replace(" ", "")
    if row_ref_compact and len(row_ref_compact) >= 3 and row_ref_compact in name_compact:
        score += 95

    if ref_norm and row_ref and ref_norm == row_ref:
        score += 220

    if ref_compact and row_ref_compact and ref_compact == row_ref_compact:
        score += 200

    strong_hits = 0
    for token in name_tokens:
        if len(token) >= 3 and token in blob_tokens:
            strong_hits += 1
    score += strong_hits * 12

    if blob_compact and name_compact and row_name_compact and row_name_compact in name_compact:
        score += 80

    if row.get("image_url"):
        score += 3
    if row.get("pdf_url"):
        score += 2

    return score
def _classify_pdf_kind(pdf_url: str) -> tuple[str, str]:
    low = clean_spaces(pdf_url).lower()

    if "datasheet" in low:
        return "resolved_ficha_tecnica", "ficha_tecnica"

    return "resolved_catalogo_producto", "catalogo_producto"


def _build_not_found(reference: str, name: str) -> dict:
    return {
        "resolver_status": "not_found",
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
        "notes": "calpeda_no_search_text_match",
    }
def resolve_reference(reference: str, name: str, catalog_rows: list[dict]) -> dict:
    reference = clean_spaces(reference)
    name = clean_spaces(name)

    if not catalog_rows:
        result = _build_not_found(reference, name)
        result["notes"] = "calpeda_catalog_empty"
        return result

    best_row = None
    best_score = -1

    for row in catalog_rows:
        score = _score_row(reference, name, row)
        if score > best_score:
            best_score = score
            best_row = row

    if best_row is None or best_score < 35:
        return _build_not_found(reference, name)

    image_url = clean_spaces(best_row.get("image_url", ""))
    pdf_url = clean_spaces(best_row.get("pdf_url", ""))
    matched_name = clean_spaces(best_row.get("name", ""))
    matched_ref = clean_spaces(best_row.get("supplier_ref", ""))
    source_url = clean_spaces(best_row.get("source_url", ""))

    if pdf_url:
        resolver_status, preferred_pdf_kind = _classify_pdf_kind(pdf_url)
        preferred_doc_type = preferred_pdf_kind
        preferred_title = matched_name
    elif image_url:
        resolver_status = "resolved_image_only"
        preferred_pdf_kind = ""
        preferred_doc_type = ""
        preferred_title = ""
    else:
        resolver_status = "not_found"
        preferred_pdf_kind = ""
        preferred_doc_type = ""
        preferred_title = ""

    return {
        "resolver_status": resolver_status,
        "reference": reference,
        "name": name,
        "matched_catalog_name": matched_name,
        "matched_catalog_ref": matched_ref,
        "matched_catalog_score": str(best_score),
        "product_page_url": source_url,
        "product_page_title": matched_name,
        "resolved_image_url": image_url,
        "preferred_pdf_kind": preferred_pdf_kind,
        "preferred_pdf_label": matched_name if pdf_url else "",
        "preferred_pdf_url": pdf_url,
        "preferred_pdf_check_ok": "",
        "preferred_pdf_content_type": "",
        "preferred_doc_type": preferred_doc_type,
        "preferred_title": preferred_title,
        "fallback_doc_type": "",
        "fallback_title": "",
        "fallback_pdf_url": "",
        "notes": "calpeda_search_text_match",
    }
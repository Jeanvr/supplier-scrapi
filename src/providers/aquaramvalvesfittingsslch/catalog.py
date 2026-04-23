from __future__ import annotations

import json
from pathlib import Path

from src.core.text import clean_spaces


VALID_PDF_KINDS = {"ficha_tecnica", "catalogo_producto"}
AQUARAM_GREEN_BALL_VALVE_IMAGE_URL = "http://www.aquaram.com/cache/e/3/d/5/0/e3d50a1be8cd2f979864706685df4a0803539e3b.png"
AQUARAM_GREEN_BALL_VALVE_SOURCE_URL = "https://www.aquaram.com/en/productos/ball-vale/2-way-ball-valve/2"


def classify_document_kind(row: dict) -> str:
    explicit_kind = clean_spaces(row.get("pdf_kind", "")).lower()
    if explicit_kind in VALID_PDF_KINDS:
        return explicit_kind

    doc_type = clean_spaces(row.get("pdf_doc_type", "")).lower()
    if doc_type in {"ficha_tecnica", "datasheet", "data_booklet", "catalogo_tecnico"}:
        return "ficha_tecnica"
    if clean_spaces(row.get("pdf_url", "")):
        return "catalogo_producto"
    return ""


def _normalize_catalog_row(row: dict) -> dict:
    normalized_row = dict(row)
    normalized_row["brand"] = clean_spaces(normalized_row.get("brand", "")) or "aquaramvalvesfittingsslch"
    normalized_row["supplier_ref"] = clean_spaces(normalized_row.get("supplier_ref", ""))
    normalized_row["name"] = clean_spaces(normalized_row.get("name", ""))
    normalized_row["source_url"] = clean_spaces(normalized_row.get("source_url", ""))
    normalized_row["image_url"] = clean_spaces(normalized_row.get("image_url", ""))
    name_upper = normalized_row["name"].upper()
    if not normalized_row["image_url"] and "VALVULA BOLA" in name_upper and "MANETA VERDA" in name_upper:
        normalized_row["image_url"] = AQUARAM_GREEN_BALL_VALVE_IMAGE_URL
        normalized_row["source_url"] = AQUARAM_GREEN_BALL_VALVE_SOURCE_URL
    normalized_row["pdf_url"] = clean_spaces(normalized_row.get("pdf_url", ""))
    normalized_row["pdf_title"] = clean_spaces(normalized_row.get("pdf_title", ""))
    normalized_row["pdf_language"] = clean_spaces(normalized_row.get("pdf_language", ""))
    normalized_row["pdf_doc_type"] = clean_spaces(normalized_row.get("pdf_doc_type", ""))
    normalized_row["search_text"] = clean_spaces(normalized_row.get("search_text", ""))
    normalized_row["pdf_kind"] = classify_document_kind(normalized_row)
    return normalized_row


def load_catalog_rows(catalog_path: Path) -> list[dict]:
    if not catalog_path.exists():
        return []

    rows: list[dict] = []
    for line in catalog_path.read_text(encoding="utf-8").splitlines():
        line = clean_spaces(line)
        if not line:
            continue
        rows.append(_normalize_catalog_row(json.loads(line)))

    return rows

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from src.core.text import clean_spaces


VALID_PDF_KINDS = {"ficha_tecnica", "catalogo_producto"}

REJECTED_DOC_MARKERS = (
    "spare part",
    "spare parts",
    "repuestos",
    "service kit",
    "service parts",
)

TECH_DOC_MARKERS = (
    "product center print pdf",
    "product centre print pdf",
    "product center pdf",
    "product centre pdf",
    "print getpdf",
    "print get pdf",
    "ticketresults pdf",
    "grundfos product centre",
    "grundfos product center",
    "grundfos caps",
    "wincaps",
    "document print engine",
    "data booklet",
    "data sheet",
    "datasheet",
    "technical data",
    "technical catalog",
    "technical catalogue",
    "catalogo tecnico",
    "catalogo tecnico",
    "catálogo técnico",
    "datenheft",
    "ficha tecnica",
    "ficha técnica",
)

PRODUCT_DOC_MARKERS = (
    "product brochure",
    "brochure",
    "catalogo de producto",
    "catalogo producto",
    "catálogo de producto",
    "catálogo producto",
    "commercial catalog",
    "commercial catalogue",
    "catalogo comercial",
    "catálogo comercial",
)

MAINTENANCE_DOC_MARKERS = (
    "instrucciones de mantenimiento",
    "maintenance instructions",
    "maintenance manual",
    "service instructions",
    "service manual",
    "mantenimiento",
)

MANUAL_DOC_MARKERS = (
    "installation and operating instructions",
    "installing and operating instructions",
    "instrucciones de instalacion y funcionamiento",
    "instrucciones de instalación y funcionamiento",
    "instrucciones de instalacion y operacion",
    "instrucciones de instalación y operación",
    "manual de instalacion",
    "manual de instalación",
)

QUICK_GUIDE_MARKERS = (
    "quick guide",
    "guia rapida",
    "guía rápida",
)

SPANISH_LANG_MARKERS = (
    "espanol",
    "spanish",
    "es mx",
    "es es",
)

ENGLISH_LANG_MARKERS = (
    "english",
    "en gb",
    "en us",
)

EXPLICIT_DOC_TYPE_MAP = {
    "product center print pdf": "product_center_print_pdf",
    "product centre print pdf": "product_center_print_pdf",
    "product_center_print_pdf": "product_center_print_pdf",
    "product center pdf": "product_center_print_pdf",
    "product centre pdf": "product_center_print_pdf",
    "product_center_pdf": "product_center_print_pdf",
    "wincaps_product_sheet": "product_center_print_pdf",
    "data booklet": "data_booklet",
    "data_booklet": "data_booklet",
    "data sheet": "data_sheet",
    "data_sheet": "data_sheet",
    "datasheet": "data_sheet",
    "technical catalogue": "catalogo_tecnico",
    "technical catalog": "catalogo_tecnico",
    "technical_catalogue": "catalogo_tecnico",
    "technical_catalog": "catalogo_tecnico",
    "catalogo tecnico": "catalogo_tecnico",
    "catálogo técnico": "catalogo_tecnico",
    "catalogo_tecnico": "catalogo_tecnico",
    "brochure": "catalogo_producto",
    "product brochure": "catalogo_producto",
    "catalogo producto": "catalogo_producto",
    "catálogo producto": "catalogo_producto",
    "catalogo de producto": "catalogo_producto",
    "catálogo de producto": "catalogo_producto",
    "catalogo comercial": "catalogo_producto",
    "catálogo comercial": "catalogo_producto",
    "catalogo_producto": "catalogo_producto",
    "manual instalacion funcionamiento": "manual_instalacion_funcionamiento",
    "manual de instalacion": "manual_instalacion_funcionamiento",
    "manual de instalación": "manual_instalacion_funcionamiento",
    "manual_instalacion_funcionamiento": "manual_instalacion_funcionamiento",
    "manual mantenimiento": "manual_mantenimiento",
    "manual de mantenimiento": "manual_mantenimiento",
    "manual_mantenimiento": "manual_mantenimiento",
    "instrucciones de mantenimiento": "manual_mantenimiento",
    "guia rapida": "guia_rapida",
    "guía rápida": "guia_rapida",
    "quick guide": "guia_rapida",
    "guia_rapida": "guia_rapida",
}


def _normalize_doc_text(value: object) -> str:
    text = clean_spaces(value)
    if not text:
        return ""

    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _document_blob(
    *,
    title: str = "",
    url: str = "",
    doc_type: str = "",
    kind: str = "",
    language: str = "",
    file_name: str = "",
) -> str:
    return " ".join(
        part
        for part in (
            _normalize_doc_text(title),
            _normalize_doc_text(url),
            _normalize_doc_text(doc_type),
            _normalize_doc_text(kind),
            _normalize_doc_text(language),
            _normalize_doc_text(file_name),
        )
        if part
    )


def detect_document_language(
    *,
    title: str = "",
    url: str = "",
    doc_type: str = "",
    kind: str = "",
    language: str = "",
    file_name: str = "",
) -> str:
    explicit_language = _normalize_doc_text(language)
    if explicit_language.startswith("es") or explicit_language == "spanish":
        return "es"
    if explicit_language.startswith("en") or explicit_language == "english":
        return "en"

    blob = _document_blob(
        title=title,
        url=url,
        doc_type=doc_type,
        kind=kind,
        language=language,
        file_name=file_name,
    )
    if any(marker in blob for marker in SPANISH_LANG_MARKERS):
        return "es"
    if any(marker in blob for marker in ENGLISH_LANG_MARKERS):
        return "en"
    return ""


def is_excluded_document(
    *,
    title: str = "",
    url: str = "",
    doc_type: str = "",
    kind: str = "",
    language: str = "",
    file_name: str = "",
) -> bool:
    blob = _document_blob(
        title=title,
        url=url,
        doc_type=doc_type,
        kind=kind,
        language=language,
        file_name=file_name,
    )
    return any(marker in blob for marker in REJECTED_DOC_MARKERS)


def detect_document_type(
    *,
    title: str = "",
    url: str = "",
    doc_type: str = "",
    kind: str = "",
    language: str = "",
    file_name: str = "",
) -> str:
    normalized_doc_type = _normalize_doc_text(doc_type)
    if normalized_doc_type in EXPLICIT_DOC_TYPE_MAP:
        return EXPLICIT_DOC_TYPE_MAP[normalized_doc_type]

    blob = _document_blob(
        title=title,
        url=url,
        doc_type=doc_type,
        kind=kind,
        language=language,
        file_name=file_name,
    )
    if any(marker in blob for marker in TECH_DOC_MARKERS):
        if any(
            marker in blob
            for marker in (
                "product center print pdf",
                "product centre print pdf",
                "product center pdf",
                "product centre pdf",
                "print getpdf",
                "print get pdf",
                "ticketresults pdf",
                "grundfos product centre",
                "grundfos product center",
                "grundfos caps",
                "wincaps",
                "document print engine",
            )
        ):
            return "product_center_print_pdf"
        if "data booklet" in blob:
            return "data_booklet"
        if "data sheet" in blob or "datasheet" in blob:
            return "data_sheet"
        return "catalogo_tecnico"
    if any(marker in blob for marker in PRODUCT_DOC_MARKERS):
        return "catalogo_producto"
    if any(marker in blob for marker in MAINTENANCE_DOC_MARKERS):
        return "manual_mantenimiento"
    if any(marker in blob for marker in MANUAL_DOC_MARKERS):
        return "manual_instalacion_funcionamiento"
    if any(marker in blob for marker in QUICK_GUIDE_MARKERS):
        return "guia_rapida"
    return ""


def classify_document_kind(
    *,
    title: str = "",
    url: str = "",
    doc_type: str = "",
    kind: str = "",
    language: str = "",
    file_name: str = "",
) -> str:
    if is_excluded_document(
        title=title,
        url=url,
        doc_type=doc_type,
        kind=kind,
        language=language,
        file_name=file_name,
    ):
        return ""

    detected_type = detect_document_type(
        title=title,
        url=url,
        doc_type=doc_type,
        kind=kind,
        language=language,
        file_name=file_name,
    )
    if detected_type in {
        "product_center_print_pdf",
        "data_booklet",
        "data_sheet",
        "catalogo_tecnico",
    }:
        return "ficha_tecnica"
    if detected_type in {
        "catalogo_producto",
        "manual_instalacion_funcionamiento",
        "manual_mantenimiento",
        "guia_rapida",
    }:
        return "catalogo_producto"

    explicit_kind = clean_spaces(kind).lower()
    if explicit_kind in VALID_PDF_KINDS:
        return explicit_kind
    return ""


def score_document(
    *,
    title: str = "",
    url: str = "",
    doc_type: str = "",
    kind: str = "",
    language: str = "",
    file_name: str = "",
) -> int:
    if not clean_spaces(url) and not clean_spaces(file_name):
        return -1000

    generic_literature_url = clean_spaces(url).lower()
    if (
        clean_spaces(kind)
        and not clean_spaces(title)
        and not clean_spaces(doc_type)
        and re.search(r"grundfosliterature-\d+\.pdf$", generic_literature_url)
    ):
        return 0

    if is_excluded_document(
        title=title,
        url=url,
        doc_type=doc_type,
        kind=kind,
        language=language,
        file_name=file_name,
    ):
        return -1000

    detected_type = detect_document_type(
        title=title,
        url=url,
        doc_type=doc_type,
        kind=kind,
        language=language,
        file_name=file_name,
    )
    resolved_language = detect_document_language(
        title=title,
        url=url,
        doc_type=doc_type,
        kind=kind,
        language=language,
        file_name=file_name,
    )

    score = 0
    if resolved_language == "es":
        score += 2000
    elif resolved_language == "en":
        score += 800

    if detected_type == "product_center_print_pdf":
        score += 2500
    elif detected_type in {"data_booklet", "data_sheet", "catalogo_tecnico"}:
        score += 1800
    elif detected_type == "catalogo_producto":
        score += 1400
    elif detected_type == "manual_instalacion_funcionamiento":
        score += 400
    elif detected_type == "manual_mantenimiento":
        score += 300
    elif detected_type == "guia_rapida":
        score += 200
    else:
        score += 10

    return score


def _iter_document_candidates(row: dict):
    document_candidates = row.get("document_candidates")
    if isinstance(document_candidates, list):
        for candidate in document_candidates:
            if isinstance(candidate, dict):
                yield candidate
        return

    pdf_url = clean_spaces(row.get("pdf_url", ""))
    if not pdf_url:
        return

    yield {
        "url": pdf_url,
        "title": clean_spaces(row.get("pdf_title", "")),
        "kind": clean_spaces(row.get("pdf_kind", "")),
        "language": clean_spaces(row.get("pdf_language", "")),
        "doc_type": clean_spaces(row.get("pdf_doc_type", "")),
    }


def _normalize_catalog_row(row: dict) -> dict:
    normalized_row = dict(row)
    best_candidate: dict | None = None
    best_score = -1000

    for candidate in _iter_document_candidates(normalized_row):
        candidate_url = clean_spaces(candidate.get("url", ""))
        score = score_document(
            title=clean_spaces(candidate.get("title", "")),
            url=candidate_url,
            doc_type=clean_spaces(candidate.get("doc_type", "")),
            kind=clean_spaces(candidate.get("kind", "")),
            language=clean_spaces(candidate.get("language", "")),
            file_name=Path(candidate_url).name,
        )
        if score > best_score:
            best_score = score
            best_candidate = candidate

    if best_candidate is None or best_score < 120:
        normalized_row["pdf_url"] = ""
        normalized_row["pdf_kind"] = ""
        normalized_row["pdf_title"] = ""
        normalized_row["pdf_language"] = ""
        normalized_row["pdf_doc_type"] = ""
        return normalized_row

    pdf_url = clean_spaces(best_candidate.get("url", ""))
    pdf_title = clean_spaces(best_candidate.get("title", ""))
    pdf_doc_type = clean_spaces(best_candidate.get("doc_type", ""))
    pdf_language = clean_spaces(best_candidate.get("language", ""))
    detected_type = detect_document_type(
        title=pdf_title,
        url=pdf_url,
        doc_type=pdf_doc_type,
        kind=clean_spaces(best_candidate.get("kind", "")),
        language=pdf_language,
        file_name=Path(pdf_url).name,
    )
    pdf_kind = classify_document_kind(
        title=pdf_title,
        url=pdf_url,
        doc_type=pdf_doc_type or detected_type,
        kind=clean_spaces(best_candidate.get("kind", "")),
        language=pdf_language,
        file_name=Path(pdf_url).name,
    )

    normalized_row["pdf_url"] = pdf_url
    normalized_row["pdf_title"] = pdf_title
    normalized_row["pdf_doc_type"] = pdf_doc_type or detected_type
    normalized_row["pdf_language"] = pdf_language or detect_document_language(
        title=pdf_title,
        url=pdf_url,
        doc_type=pdf_doc_type or detected_type,
        kind=pdf_kind,
        file_name=Path(pdf_url).name,
    )
    normalized_row["pdf_kind"] = pdf_kind
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

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from src.core.text import clean_spaces


VALID_PDF_KINDS = {"ficha_tecnica", "catalogo_producto"}

EXCLUDED_DOC_MARKERS = (
    "installation and operating instructions",
    "installing and operating instructions",
    "instructions de installation",
    "instrucciones de instalacion y funcionamiento",
    "instrucciones de instalación y funcionamiento",
    "instrucciones de mantenimiento",
    "maintenance instructions",
    "service instructions",
    "service kit",
    "safety instructions",
    "quick guide",
    "guia rapida",
    "guía rápida",
    "spare part",
    "spare parts",
    "repuestos",
    "manual",
    "mantenimiento",
    "maintenance",
)

TECH_DOC_MARKERS = (
    "data booklet",
    "data sheet",
    "datasheet",
    "technical data",
    "technical catalog",
    "technical catalogue",
    "catalogo tecnico",
    "catálogo técnico",
    "catalogue technique",
    "catalogo tecnico",
    "datenheft",
    "ficha tecnica",
    "ficha técnica",
)

PRODUCT_DOC_MARKERS = (
    "product brochure",
    "brochure",
    "catalogo de producto",
    "catálogo de producto",
    "catalogo producto",
    "catálogo producto",
    "catalogue produit",
    "commercial catalog",
    "commercial catalogue",
    "catalogo comercial",
    "catálogo comercial",
)

SPANISH_LANG_MARKERS = (
    "español",
    "espanol",
    "(es)",
    "spanish",
    "/es/",
    "es-es",
    "es-mx",
)

ENGLISH_LANG_MARKERS = (
    "english",
    "(en)",
    "en-gb",
    "en-us",
    "/en/",
)


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
    if explicit_language in {"es", "spanish"}:
        return "es"
    if explicit_language in {"en", "english"}:
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
    return any(marker in blob for marker in EXCLUDED_DOC_MARKERS)


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

    explicit_kind = clean_spaces(kind).lower()
    if explicit_kind in VALID_PDF_KINDS:
        return explicit_kind

    blob = _document_blob(
        title=title,
        url=url,
        doc_type=doc_type,
        kind=kind,
        language=language,
        file_name=file_name,
    )
    if any(marker in blob for marker in TECH_DOC_MARKERS):
        return "ficha_tecnica"
    if any(marker in blob for marker in PRODUCT_DOC_MARKERS):
        return "catalogo_producto"
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

    resolved_kind = classify_document_kind(
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
    if resolved_kind == "ficha_tecnica":
        score += 300
    elif resolved_kind == "catalogo_producto":
        score += 200

    if resolved_language == "es":
        score += 40
    elif resolved_language == "en":
        score += 20

    blob = _document_blob(
        title=title,
        url=url,
        doc_type=doc_type,
        kind=kind,
        language=language,
        file_name=file_name,
    )
    if "data booklet" in blob or "data sheet" in blob:
        score += 25
    elif "catalogo tecnico" in blob or "catálogo técnico" in blob or "technical data" in blob:
        score += 20

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

    if best_candidate is None or best_score < 180:
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
    pdf_kind = classify_document_kind(
        title=pdf_title,
        url=pdf_url,
        doc_type=pdf_doc_type,
        kind=clean_spaces(best_candidate.get("kind", "")),
        language=pdf_language,
        file_name=Path(pdf_url).name,
    )

    normalized_row["pdf_url"] = pdf_url
    normalized_row["pdf_title"] = pdf_title
    normalized_row["pdf_doc_type"] = pdf_doc_type
    normalized_row["pdf_language"] = pdf_language or detect_document_language(
        title=pdf_title,
        url=pdf_url,
        doc_type=pdf_doc_type,
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

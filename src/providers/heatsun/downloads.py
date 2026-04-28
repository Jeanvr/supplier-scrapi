from __future__ import annotations

import re
from pathlib import Path

from src.core.pdf_tools.pdf_operations import (
    extract_pdf_text,
    find_reference_pages,
    merge_selected_pages,
)
from src.core.text import clean_spaces
from src.providers.simple_downloads import attach_downloads as attach_simple_downloads


CATALOG_PDF_NAME = "HEATSUN_sistema-pressfiting.pdf"
_PDF_TEXT_CACHE: dict[str, list[str]] = {}
_MODEL_RE = re.compile(r"\bTV[EL]-\d+\b", re.IGNORECASE)


def _append_download_note(result: dict, note: str) -> None:
    existing_notes = clean_spaces(result.get("download_notes", ""))
    result["download_notes"] = " | ".join(part for part in [existing_notes, note] if part)


def _resolve_local_pdf(path_str: str) -> Path | None:
    path_str = clean_spaces(path_str)
    if not path_str:
        return None

    candidate = Path(path_str)
    if candidate.is_file():
        return candidate

    repo_candidate = Path.cwd() / candidate
    if repo_candidate.is_file():
        return repo_candidate

    return None


def _is_heatsun_catalog_pdf(result: dict) -> bool:
    preferred_pdf_url = clean_spaces(result.get("preferred_pdf_url", ""))
    downloaded_pdf_url = clean_spaces(result.get("downloaded_pdf_url", ""))
    return CATALOG_PDF_NAME in preferred_pdf_url or CATALOG_PDF_NAME in downloaded_pdf_url


def _pdf_pages(pdf_path: Path, cache_key: str) -> list[str]:
    cached = _PDF_TEXT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    pages = extract_pdf_text(pdf_path)
    _PDF_TEXT_CACHE[cache_key] = pages
    return pages


def _extract_model_candidates(*values: str) -> list[str]:
    found: list[str] = []
    for value in values:
        for match in _MODEL_RE.findall(clean_spaces(value).upper()):
            if match not in found:
                found.append(match)
    return found


def _candidate_terms(reference: str, result: dict) -> list[str]:
    candidates: list[str] = []

    for model in _extract_model_candidates(
        clean_spaces(result.get("matched_catalog_name", "")),
        clean_spaces(result.get("name", "")),
    ):
        candidates.append(model)

    for ref_value in [
        clean_spaces(reference),
        clean_spaces(result.get("matched_catalog_ref", "")),
    ]:
        ref_value = ref_value.replace(" ", "").upper()
        if re.fullmatch(r"\d{7}", ref_value) and ref_value not in candidates:
            candidates.append(ref_value)

    return candidates


def _trim_catalog_pdf_for_reference(result: dict, reference: str) -> None:
    if not _is_heatsun_catalog_pdf(result):
        return

    output_pdf = _resolve_local_pdf(clean_spaces(result.get("local_pdf", "")))
    if output_pdf is None:
        return

    candidates = _candidate_terms(reference, result)
    if not candidates:
        _append_download_note(result, "pdf:catalog_full_ref_not_found reason=no_trim_evidence")
        return

    cache_key = clean_spaces(result.get("downloaded_pdf_url", "")) or clean_spaces(result.get("preferred_pdf_url", ""))
    try:
        pages = _pdf_pages(output_pdf, cache_key)
    except Exception as exc:
        _append_download_note(result, f"pdf:catalog_full_ref_not_found reason=page_detection_error:{exc}")
        return

    matched_candidate = ""
    reference_pages: list[int] = []
    for candidate in candidates:
        reference_pages = find_reference_pages(candidate, pages)
        if reference_pages:
            matched_candidate = candidate
            break

    if not reference_pages:
        _append_download_note(result, "pdf:catalog_full_ref_not_found")
        return

    selected_pages = reference_pages[:1]
    temp_output = output_pdf.with_suffix(".trim.tmp.pdf")
    try:
        merge_selected_pages(output_pdf, selected_pages, temp_output)
        if temp_output.stat().st_size >= output_pdf.stat().st_size:
            temp_output.unlink(missing_ok=True)
            _append_download_note(result, "pdf:catalog_full_ref_not_found reason=trim_not_smaller")
            return

        temp_output.replace(output_pdf)
        _append_download_note(result, "pdf:trimmed_catalog")
        _append_download_note(result, f"pdf:trimmed_by_ref:{matched_candidate}")
    except Exception as exc:
        temp_output.unlink(missing_ok=True)
        _append_download_note(result, f"pdf:catalog_full_ref_not_found reason=trim_write_error:{exc}")


def attach_downloads(
    result: dict,
    reference: str,
    name: str,
    download_enabled: bool,
    images_dir: Path,
    pdfs_dir: Path,
) -> dict:
    result = attach_simple_downloads(
        result=result,
        reference=reference,
        name=name,
        download_enabled=download_enabled,
        images_dir=images_dir,
        pdfs_dir=pdfs_dir,
    )

    if not download_enabled:
        return result

    _trim_catalog_pdf_for_reference(result, clean_spaces(reference))
    return result

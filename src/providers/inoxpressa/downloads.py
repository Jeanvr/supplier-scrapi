from __future__ import annotations

from pathlib import Path

from src.core.pdf_tools.pdf_operations import (
    extract_pdf_text,
    find_reference_pages,
    merge_selected_pages,
)
from src.core.text import clean_spaces
from src.providers.simple_downloads import attach_downloads as attach_simple_downloads


CATALOG_PDF_NAME = "CATALOGO_GENERAL_V2022_HD.pdf"
_PDF_TEXT_CACHE: dict[str, list[str]] = {}


def _append_note(result: dict, note: str) -> None:
    existing_notes = clean_spaces(result.get("notes", ""))
    result["notes"] = " | ".join(part for part in [existing_notes, note] if part)


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


def _is_inoxpres_catalog_pdf(result: dict) -> bool:
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


def _candidate_references(reference: str) -> list[str]:
    reference = clean_spaces(reference).upper().replace(" ", "")
    candidates = [reference]

    # Inoxpres catalog prints 62V2CQ* valve references as 62V2C*.
    if reference.startswith("62V2CQ"):
        candidates.append(reference.replace("62V2CQ", "62V2C", 1))

    return list(dict.fromkeys(candidates))


def _fallback_family_pages(reference: str, pages: list[str]) -> list[int]:
    ref = clean_spaces(reference).upper().replace(" ", "")

    found: list[int] = []
    for idx, text in enumerate(pages):
        upper_text = text.upper()

        if ref.startswith("20EPDM"):
            if "JUNTA PLANA ACOPLE" in upper_text and "EPDM" in upper_text:
                found.append(idx)

        elif ref.startswith("62V2CQ"):
            # The family page contains all 62V2C* sizes.
            if "62V2C015" in upper_text or ("VÁLVULAS DE BOLA" in upper_text and "62V2C" in upper_text):
                found.append(idx)

    return found


def _trim_catalog_pdf_for_reference(result: dict, reference: str) -> None:
    if not _is_inoxpres_catalog_pdf(result):
        return

    output_pdf = _resolve_local_pdf(clean_spaces(result.get("local_pdf", "")))
    if output_pdf is None:
        _append_note(result, "pdf:catalog_full_ref_not_found")
        return

    cache_key = clean_spaces(result.get("downloaded_pdf_url", "")) or clean_spaces(result.get("preferred_pdf_url", ""))

    try:
        pages = _pdf_pages(output_pdf, cache_key)
        reference_pages: list[int] = []
        matched_reference = clean_spaces(reference)

        for candidate in _candidate_references(reference):
            reference_pages = find_reference_pages(candidate, pages)
            if reference_pages:
                matched_reference = candidate
                if candidate != clean_spaces(reference).upper().replace(" ", ""):
                    _append_note(result, f"pdf:trimmed_by_alt_ref:{candidate}")
                break

        if not reference_pages:
            reference_pages = _fallback_family_pages(reference, pages)
            if reference_pages:
                _append_note(result, "pdf:trimmed_by_family_fallback")

    except Exception as exc:
        _append_note(result, f"pdf:catalog_full_ref_not_found reason=page_detection_error:{exc}")
        return

    if not reference_pages:
        _append_note(result, "pdf:catalog_full_ref_not_found")
        return

    selected_pages = reference_pages[:1]
    temp_output = output_pdf.with_suffix(".trim.tmp.pdf")

    try:
        merge_selected_pages(output_pdf, selected_pages, temp_output)

        if temp_output.stat().st_size >= output_pdf.stat().st_size:
            temp_output.unlink(missing_ok=True)
            _append_note(result, "pdf:catalog_full_ref_not_found reason=trim_not_smaller")
            return

        temp_output.replace(output_pdf)
        _append_note(result, "pdf:trimmed_catalog")
        _append_note(result, f"pdf:trimmed_by_ref:{matched_reference}")

    except Exception as exc:
        temp_output.unlink(missing_ok=True)
        _append_note(result, f"pdf:catalog_full_ref_not_found reason=trim_write_error:{exc}")

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

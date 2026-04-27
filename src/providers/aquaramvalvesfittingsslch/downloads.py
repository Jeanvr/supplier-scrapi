from __future__ import annotations

import shutil
from pathlib import Path

from src.core.pdf_tools.pdf_operations import (
    extract_pdf_text,
    find_reference_pages,
    merge_selected_pages,
)
from src.core.text import clean_spaces
from src.providers.simple_downloads import attach_downloads as attach_simple_downloads


CATALOG_PDF = Path("data/catalogs/aquaramvalvesfittingsslch_catalog.pdf")
_PDF_TEXT_CACHE: dict[Path, list[str]] = {}


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


def _append_note(result: dict, note: str) -> None:
    existing_notes = clean_spaces(result.get("notes", ""))
    result["notes"] = " | ".join(part for part in [existing_notes, note] if part)


def _get_pdf_pages(pdf_path: Path) -> list[str]:
    cache_key = pdf_path.resolve()
    cached = _PDF_TEXT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    pages = extract_pdf_text(pdf_path)
    _PDF_TEXT_CACHE[cache_key] = pages
    return pages


def _trim_catalog_pdf_for_reference(result: dict, reference: str) -> None:
    source_pdf = _resolve_local_pdf(clean_spaces(result.get("preferred_pdf_url", "")))
    output_pdf = _resolve_local_pdf(clean_spaces(result.get("local_pdf", "")))
    if source_pdf is None or output_pdf is None:
        _append_note(result, "pdf:full_catalog_fallback reason=missing_local_pdf_path")
        return

    if source_pdf.resolve() != (Path.cwd() / CATALOG_PDF).resolve():
        _append_note(result, "pdf:full_catalog_fallback reason=non_aquaram_catalog_pdf")
        return

    try:
        pages = _get_pdf_pages(source_pdf)
        reference_pages = find_reference_pages(reference, pages)
    except Exception as exc:
        _append_note(result, f"pdf:full_catalog_fallback reason=page_detection_error:{exc}")
        return

    if not reference_pages:
        _append_note(result, "pdf:full_catalog_fallback reason=ref_not_found_in_pdf")
        return

    temp_output = output_pdf.with_suffix(".trim.tmp.pdf")
    try:
        merge_selected_pages(source_pdf, reference_pages, temp_output)
        if temp_output.stat().st_size >= source_pdf.stat().st_size:
            _append_note(result, "pdf:full_catalog_fallback reason=trim_not_smaller")
            temp_output.unlink(missing_ok=True)
            return

        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        temp_output.replace(output_pdf)
        pages_label = ",".join(str(page) for page in reference_pages)
        _append_note(result, f"pdf:trimmed_catalog pages={pages_label}")
    except Exception as exc:
        temp_output.unlink(missing_ok=True)
        if not output_pdf.exists() and source_pdf.exists():
            shutil.copyfile(source_pdf, output_pdf)
        _append_note(result, f"pdf:full_catalog_fallback reason=trim_write_error:{exc}")


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

    if clean_spaces(result.get("local_pdf", "")):
        _trim_catalog_pdf_for_reference(result, clean_spaces(reference))

    return result

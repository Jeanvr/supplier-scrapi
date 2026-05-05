from __future__ import annotations

from pathlib import Path

from src.core.pdf_tools.pdf_operations import extract_pdf_text, find_reference_pages, merge_selected_pages
from src.core.text import clean_spaces
from src.providers.bosch.media import build_download_paths


CATALOG_PDF = Path("data/catalogs/acfix_catalog.pdf")
_PDF_TEXT_CACHE: dict[Path, list[str]] = {}


def _append_note(result: dict, note: str) -> None:
    existing_notes = clean_spaces(result.get("notes", ""))
    parts = [clean_spaces(part) for part in existing_notes.split("|") if clean_spaces(part)]
    if note not in parts:
        parts.append(note)
    result["notes"] = " | ".join(parts)


def _append_download_note(result: dict, note: str) -> None:
    existing_notes = clean_spaces(result.get("download_notes", ""))
    parts = [clean_spaces(part) for part in existing_notes.split("|") if clean_spaces(part)]
    if note not in parts:
        parts.append(note)
    result["download_notes"] = " | ".join(parts)


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


def _get_pdf_pages(pdf_path: Path) -> list[str]:
    cache_key = pdf_path.resolve()
    cached = _PDF_TEXT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    pages = extract_pdf_text(pdf_path)
    _PDF_TEXT_CACHE[cache_key] = pages
    return pages


def _set_download_status(result: dict) -> None:
    if clean_spaces(result.get("local_pdf", "")):
        result["download_status"] = "downloaded_pdf_only"
    elif clean_spaces(result.get("preferred_pdf_url", "")):
        result["download_status"] = "download_failed"
    else:
        result["download_status"] = "nothing_to_download"


def _catalog_page(result: dict) -> int | None:
    raw_page = clean_spaces(result.get("catalog_page", ""))
    if not raw_page.isdigit():
        return None
    page = int(raw_page)
    return page if page > 0 else None


def _select_reference_page(result: dict, source_pdf: Path, reference: str) -> int | None:
    matched_ref = clean_spaces(result.get("matched_catalog_ref", "")) or clean_spaces(reference)
    pages_text = _get_pdf_pages(source_pdf)
    reference_pages = find_reference_pages(matched_ref, pages_text)
    catalog_page = _catalog_page(result)
    if catalog_page and catalog_page in reference_pages:
        return catalog_page
    return reference_pages[0] if reference_pages else None


def attach_downloads(
    result: dict,
    reference: str,
    name: str,
    download_enabled: bool,
    images_dir: Path,
    pdfs_dir: Path,
) -> dict:
    result["download_enabled"] = download_enabled
    result["download_status"] = "not_requested"
    result["local_image"] = ""
    result["local_pdf"] = ""
    result["downloaded_image_url"] = ""
    result["downloaded_pdf_url"] = ""
    result["download_notes"] = ""

    if not download_enabled:
        return result

    pdf_url = clean_spaces(result.get("preferred_pdf_url", ""))
    if not pdf_url:
        result["download_status"] = "nothing_to_download"
        return result

    source_pdf = _resolve_local_pdf(pdf_url) or CATALOG_PDF
    if not source_pdf.is_file():
        _append_download_note(result, "pdf:source_missing")
        _set_download_status(result)
        return result

    _image_path, pdf_path = build_download_paths(
        reference=reference,
        name=name,
        preferred_pdf_kind=clean_spaces(result.get("preferred_pdf_kind", "")),
        preferred_pdf_url=pdf_url,
        resolved_image_url="",
        images_dir=images_dir,
        pdfs_dir=pdfs_dir,
    )
    if pdf_path is None:
        _append_download_note(result, "pdf:missing_output_path")
        _set_download_status(result)
        return result

    try:
        selected_page = _select_reference_page(result, source_pdf, reference)
        if selected_page is None:
            _append_download_note(result, "pdf:ref_not_found_in_catalog")
            _set_download_status(result)
            return result

        temp_output = pdf_path.with_suffix(".tmp.pdf")
        merge_selected_pages(source_pdf, [selected_page], temp_output)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        temp_output.replace(pdf_path)
        result["local_pdf"] = str(pdf_path)
        result["downloaded_pdf_url"] = str(source_pdf)
        result["preferred_pdf_check_ok"] = "ok"
        result["preferred_pdf_content_type"] = "application/pdf"
        _append_note(result, f"acfix_catalog_page={selected_page}")
        _append_download_note(result, f"pdf:catalog_page={selected_page}")
    except Exception as exc:
        pdf_path.unlink(missing_ok=True)
        _append_download_note(result, f"pdf:error:{exc}")

    _set_download_status(result)
    return result

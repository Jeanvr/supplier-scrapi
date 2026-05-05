from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageChops, ImageOps

from src.core.pdf_tools.pdf_operations import (
    extract_pdf_text,
    find_reference_pages,
    merge_selected_pages,
)
from src.core.text import clean_spaces
from src.providers.bosch.media import build_download_paths, download_binary
from src.providers.simple_downloads import attach_downloads as attach_simple_downloads


CATALOG_PDF = Path("data/catalogs/aquaramvalvesfittingsslch_catalog.pdf")
QR_CACHE_DIR = Path("/tmp/aquaramvalvesfittingsslch_qr_cache")
_PDF_TEXT_CACHE: dict[Path, list[str]] = {}
_QR_PDF_CACHE: dict[str, Path] = {}


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
    parts = [clean_spaces(part) for part in existing_notes.split("|") if clean_spaces(part)]
    if note not in parts:
        parts.append(note)
    result["notes"] = " | ".join(parts)


def _looks_like_qr_url(value: str) -> bool:
    parsed = urlparse(clean_spaces(value))
    return parsed.scheme in {"http", "https"} and parsed.netloc.endswith("qrco.de")


def _get_pdf_pages(pdf_path: Path) -> list[str]:
    cache_key = pdf_path.resolve()
    cached = _PDF_TEXT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    pages = extract_pdf_text(pdf_path)
    _PDF_TEXT_CACHE[cache_key] = pages
    return pages


def _has_technical_sheet_text(pages: list[str]) -> bool:
    for page in pages:
        upper_page = page.upper()
        if "FICHA TÉCNICA" in upper_page or "FICHA TECNICA" in upper_page or "TECHNICAL SHEET" in upper_page:
            return True
    return False


def _get_cached_qr_pdf(qr_url: str) -> tuple[Path | None, str]:
    cached = _QR_PDF_CACHE.get(qr_url)
    if cached is not None and cached.is_file():
        return cached, ""

    QR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_name = hashlib.sha256(qr_url.encode("utf-8")).hexdigest()[:24]
    cache_path = QR_CACHE_DIR / f"{cache_name}.pdf"
    if cache_path.is_file():
        _QR_PDF_CACHE[qr_url] = cache_path
        return cache_path, ""

    temp_path = cache_path.with_suffix(".tmp")
    ok, _final_url, content_type, error = download_binary(qr_url, temp_path, accept_pdf=True)
    if not ok:
        temp_path.unlink(missing_ok=True)
        return None, error or "download_error"

    if "pdf" not in content_type and temp_path.read_bytes()[:4] != b"%PDF":
        temp_path.unlink(missing_ok=True)
        return None, f"unexpected_content_type:{content_type or 'unknown'}"

    temp_path.replace(cache_path)
    _QR_PDF_CACHE[qr_url] = cache_path
    return cache_path, ""


def _set_download_status(result: dict) -> None:
    image_ok = bool(clean_spaces(result.get("local_image", "")))
    pdf_ok = bool(clean_spaces(result.get("local_pdf", "")))
    if image_ok and pdf_ok:
        result["download_status"] = "downloaded_image_and_pdf"
    elif image_ok:
        result["download_status"] = "downloaded_image_only"
    elif pdf_ok:
        result["download_status"] = "downloaded_pdf_only"
    else:
        result["download_status"] = "download_failed"


def _append_download_note(result: dict, note: str) -> None:
    existing_notes = clean_spaces(result.get("download_notes", ""))
    parts = [clean_spaces(part) for part in existing_notes.split("|") if clean_spaces(part)]
    if note not in parts:
        parts.append(note)
    result["download_notes"] = " | ".join(parts)


def _postprocess_aquaram_image(result: dict) -> None:
    image_path = Path(clean_spaces(result.get("local_image", "")))
    if not image_path.is_file():
        return

    try:
        with Image.open(image_path) as src:
            image = ImageOps.exif_transpose(src).convert("RGB")

        bg_color = image.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
        bg = Image.new("RGB", image.size, bg_color)
        diff = ImageChops.difference(image, bg).convert("L")
        mask = diff.point(lambda value: 255 if value > 18 else 0)
        bbox = mask.getbbox()
        if bbox is None:
            _append_download_note(result, "image:aquaram_trim_skipped_empty_bbox")
            return

        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        pad = max(12, int(max(width, height) * 0.035))
        left = max(0, bbox[0] - pad)
        top = max(0, bbox[1] - pad)
        right = min(image.width, bbox[2] + pad)
        bottom = min(image.height, bbox[3] + pad)
        cropped = image.crop((left, top, right, bottom))

        canvas_size = 600
        target_extent = int(canvas_size * 0.86)
        scale = target_extent / max(cropped.size)
        resized_size = (
            max(1, int(cropped.width * scale)),
            max(1, int(cropped.height * scale)),
        )
        resized = cropped.resize(resized_size, Image.Resampling.LANCZOS)

        canvas = Image.new("RGB", (canvas_size, canvas_size), (255, 255, 255))
        x = (canvas_size - resized.width) // 2
        y = (canvas_size - resized.height) // 2
        canvas.paste(resized, (x, y))
        canvas.save(image_path, "JPEG", quality=94, optimize=True, progressive=True, subsampling=0)
        _append_download_note(result, "image:aquaram_trimmed_centered")
    except Exception as exc:
        _append_download_note(result, f"image:aquaram_trim_error:{exc}")


def _qr_trim_pages(reference_pages: list[int]) -> list[int]:
    ref_page = reference_pages[0]
    return list(dict.fromkeys([max(1, ref_page - 1), ref_page]))


def _pages_label(pages: list[int]) -> str:
    if len(pages) == 2 and pages[1] == pages[0] + 1:
        return f"{pages[0]}-{pages[1]}"
    return ",".join(str(page) for page in pages)


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


def _download_catalog_fallback(result: dict, reference: str, output_pdf: Path) -> None:
    fallback_pdf_url = clean_spaces(result.get("fallback_pdf_url", ""))
    source_pdf = _resolve_local_pdf(fallback_pdf_url) or (Path.cwd() / CATALOG_PDF)
    if not source_pdf.is_file():
        result["local_pdf"] = ""
        _append_note(result, "aquaram_qr_failed_fallback_catalog reason=missing_catalog_pdf")
        _set_download_status(result)
        return

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_pdf, output_pdf)
    result["preferred_pdf_url"] = fallback_pdf_url or str(CATALOG_PDF)
    result["preferred_pdf_kind"] = "catalogo_producto"
    result["preferred_doc_type"] = clean_spaces(result.get("fallback_doc_type", "")) or "catalogo_producto"
    result["preferred_title"] = clean_spaces(result.get("fallback_title", "")) or "Catalogo tecnico CH Aquaram 2024 ES/EN/FR"
    result["preferred_pdf_label"] = result["preferred_title"]
    result["local_pdf"] = str(output_pdf)
    result["downloaded_pdf_url"] = str(source_pdf)
    _append_note(result, "aquaram_qr_failed_fallback_catalog")
    _trim_catalog_pdf_for_reference(result, clean_spaces(reference))
    _set_download_status(result)


def _attach_qr_pdf(result: dict, reference: str, name: str, images_dir: Path, pdfs_dir: Path) -> None:
    qr_url = clean_spaces(result.get("preferred_pdf_url", ""))
    _image_path, output_pdf = build_download_paths(
        reference=reference,
        name=name,
        preferred_pdf_kind=clean_spaces(result.get("preferred_pdf_kind", "")),
        preferred_pdf_url=qr_url,
        resolved_image_url=clean_spaces(result.get("resolved_image_url", "")),
        images_dir=images_dir,
        pdfs_dir=pdfs_dir,
    )
    if output_pdf is None:
        _append_note(result, "aquaram_qr_failed_fallback_catalog reason=missing_output_path")
        _set_download_status(result)
        return

    qr_pdf, error = _get_cached_qr_pdf(qr_url)
    if qr_pdf is None:
        _append_note(result, f"aquaram_qr_failed_fallback_catalog reason={error}")
        _download_catalog_fallback(result, reference, output_pdf)
        return

    try:
        pages = _get_pdf_pages(qr_pdf)
        reference_pages = find_reference_pages(reference, pages)
        has_technical_sheet = _has_technical_sheet_text(pages)
    except Exception as exc:
        _append_note(result, f"aquaram_qr_failed_fallback_catalog reason=validation_error:{exc}")
        _download_catalog_fallback(result, reference, output_pdf)
        return

    if not has_technical_sheet or not reference_pages:
        reason = "missing_technical_sheet" if not has_technical_sheet else "ref_not_found"
        _append_note(result, f"aquaram_qr_failed_fallback_catalog reason={reason}")
        _download_catalog_fallback(result, reference, output_pdf)
        return

    temp_output = output_pdf.with_suffix(".qr.trim.tmp.pdf")
    try:
        selected_pages = _qr_trim_pages(reference_pages)
        merge_selected_pages(qr_pdf, selected_pages, temp_output)
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        temp_output.replace(output_pdf)
        result["local_pdf"] = str(output_pdf)
        result["downloaded_pdf_url"] = qr_url
        result["preferred_pdf_check_ok"] = "ok"
        result["preferred_pdf_content_type"] = "application/pdf"
        _append_note(result, "aquaram_qr_ref_exact")
        _append_note(result, "aquaram_qr_pdf_preferred")
        _append_note(result, f"pdf:trimmed_qr_technical_data pages={_pages_label(selected_pages)}")
        _set_download_status(result)
    except Exception as exc:
        temp_output.unlink(missing_ok=True)
        _append_note(result, f"aquaram_qr_failed_fallback_catalog reason=trim_write_error:{exc}")
        _download_catalog_fallback(result, reference, output_pdf)


def attach_downloads(
    result: dict,
    reference: str,
    name: str,
    download_enabled: bool,
    images_dir: Path,
    pdfs_dir: Path,
) -> dict:
    qr_pdf_url = clean_spaces(result.get("preferred_pdf_url", ""))
    fallback_pdf_url = clean_spaces(result.get("fallback_pdf_url", ""))
    is_qr_pdf = _looks_like_qr_url(qr_pdf_url)

    simple_result = result
    if is_qr_pdf:
        simple_result = dict(result)
        simple_result["preferred_pdf_url"] = ""

    result = attach_simple_downloads(
        result=simple_result,
        reference=reference,
        name=name,
        download_enabled=download_enabled,
        images_dir=images_dir,
        pdfs_dir=pdfs_dir,
    )

    if is_qr_pdf:
        result["preferred_pdf_url"] = qr_pdf_url
        result["fallback_pdf_url"] = fallback_pdf_url

    if not download_enabled:
        return result

    _postprocess_aquaram_image(result)

    if is_qr_pdf:
        _attach_qr_pdf(result, clean_spaces(reference), clean_spaces(name), images_dir, pdfs_dir)
        return result

    if clean_spaces(result.get("local_pdf", "")):
        _trim_catalog_pdf_for_reference(result, clean_spaces(reference))

    return result

from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import urlparse

from src.core.text import clean_spaces
from src.providers.bosch.media import build_download_paths, download_binary, save_ecommerce_jpg


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def _resolve_local_source(path_str: str) -> Path | None:
    candidate = Path(path_str)
    if candidate.is_file():
        return candidate

    repo_relative = Path.cwd() / candidate
    if repo_relative.is_file():
        return repo_relative

    return None


def _is_pdf_file(path: Path) -> bool:
    try:
        return path.read_bytes()[:4] == b"%PDF"
    except OSError:
        return False


def _download_image(result: dict, image_url: str, image_path_base: Path, notes: list[str]) -> bool:
    if _looks_like_url(image_url):
        temp_path = image_path_base.with_suffix(".imgtmp")
        ok, final_url, _content_type, error = download_binary(image_url, temp_path, accept_pdf=False)
        if not ok:
            temp_path.unlink(missing_ok=True)
            notes.append(f"image:{error or 'unknown_error'}")
            return False

        try:
            final_image_path = save_ecommerce_jpg(temp_path, image_path_base)
            result["local_image"] = str(final_image_path)
            result["downloaded_image_url"] = final_url
            return True
        except Exception as exc:
            notes.append(f"image:convert_error:{exc}")
            return False
        finally:
            temp_path.unlink(missing_ok=True)

    local_source = _resolve_local_source(image_url)
    if local_source is None:
        notes.append("image:unsupported_source")
        return False

    try:
        final_image_path = save_ecommerce_jpg(local_source, image_path_base)
        result["local_image"] = str(final_image_path)
        result["downloaded_image_url"] = str(local_source)
        return True
    except Exception as exc:
        notes.append(f"image:convert_error:{exc}")
        return False


def _download_pdf(result: dict, pdf_url: str, pdf_path: Path, notes: list[str]) -> bool:
    if _looks_like_url(pdf_url):
        temp_pdf_path = pdf_path.with_suffix(".tmp")
        ok, final_url, content_type, error = download_binary(pdf_url, temp_pdf_path, accept_pdf=True)
        if not ok:
            temp_pdf_path.unlink(missing_ok=True)
            notes.append(f"pdf:{error or 'unknown_error'}")
            return False

        if "pdf" not in content_type and not _is_pdf_file(temp_pdf_path):
            temp_pdf_path.unlink(missing_ok=True)
            notes.append(f"pdf:unexpected_content_type:{content_type or 'unknown'}")
            return False

        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        if pdf_path.exists():
            pdf_path.unlink(missing_ok=True)
        temp_pdf_path.replace(pdf_path)
        result["local_pdf"] = str(pdf_path)
        result["downloaded_pdf_url"] = final_url
        return True

    local_source = _resolve_local_source(pdf_url)
    if local_source is None:
        notes.append("pdf:unsupported_source")
        return False

    if not _is_pdf_file(local_source):
        notes.append("pdf:local_source_not_pdf")
        return False

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(local_source, pdf_path)
    result["local_pdf"] = str(pdf_path)
    result["downloaded_pdf_url"] = str(local_source)
    return True


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

    image_url = clean_spaces(result.get("resolved_image_url", ""))
    pdf_url = clean_spaces(result.get("preferred_pdf_url", ""))

    image_path_base, pdf_path = build_download_paths(
        reference=reference,
        name=name,
        preferred_pdf_kind=clean_spaces(result.get("preferred_pdf_kind", "")),
        preferred_pdf_url=pdf_url,
        resolved_image_url=image_url,
        images_dir=images_dir,
        pdfs_dir=pdfs_dir,
    )

    notes: list[str] = []
    image_ok = False
    pdf_ok = False

    if image_url and image_path_base is not None:
        image_ok = _download_image(result, image_url, image_path_base, notes)

    if pdf_url and pdf_path is not None:
        pdf_ok = _download_pdf(result, pdf_url, pdf_path, notes)
        if not pdf_ok and pdf_path.exists():
            pdf_path.unlink(missing_ok=True)

    if image_ok and pdf_ok:
        result["download_status"] = "downloaded_image_and_pdf"
    elif image_ok and not pdf_url:
        result["download_status"] = "downloaded_image_only"
    elif image_ok and pdf_url and not pdf_ok:
        result["download_status"] = "downloaded_image_pdf_failed"
    elif pdf_ok and not image_url:
        result["download_status"] = "downloaded_pdf_only"
    elif pdf_ok and image_url and not image_ok:
        result["download_status"] = "downloaded_pdf_image_failed"
    elif image_url or pdf_url:
        result["download_status"] = "download_failed"
    else:
        result["download_status"] = "nothing_to_download"

    result["download_notes"] = " | ".join(notes)
    return result

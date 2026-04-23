from __future__ import annotations

import shutil
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from src.core.text import clean_spaces
from src.providers.bosch.media import PDF_HEADERS, build_download_paths, download_binary, save_ecommerce_jpg


PDF_SKIP_RULES = (
    ("aquaram.com/downloads/aquaram.pdf", "legacy_https_certificate"),
    ("genebre.es/documentos/catalogos/", "large_catalog_pdf"),
    ("standardhidraulica.com/docs/catalogo/", "large_catalog_pdf"),
    ("tecnotermica.es/tarifas", "large_catalog_pdf"),
    ("watts.eu/en/technical-support/data-sheet/", "commerce_pdf_blocks_automation"),
)


def _is_url(value: str) -> bool:
    return urlparse(value).scheme in {"http", "https"}


def _pdf_skip_reason(pdf_url: str) -> str:
    normalized_url = pdf_url.casefold()
    for pattern, reason in PDF_SKIP_RULES:
        if pattern in normalized_url:
            return reason
    return ""


def _copy_local_pdf(pdf_url: str, destination: Path) -> tuple[bool, str]:
    source_path = Path(pdf_url)
    if not source_path.exists():
        return False, "local_pdf_missing"

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, destination)
    return True, ""


def _download_legacy_https_pdf(url: str, destination: Path) -> tuple[bool, str, str]:
    try:
        req = Request(url, headers=PDF_HEADERS)
        context = ssl._create_unverified_context()
        with urlopen(req, timeout=45, context=context) as response:
            final_url = response.geturl()
            data = response.read()

        if not data:
            return False, final_url, "empty_response"

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return True, final_url, ""
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return False, url, f"download_error:{exc}"


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
    pdf_skipped = False

    if image_url and image_path_base is not None:
        temp_path = image_path_base.with_suffix(".imgtmp")
        ok, final_url, _content_type, error = download_binary(image_url, temp_path, accept_pdf=False)

        if ok:
            try:
                final_image_path = save_ecommerce_jpg(temp_path, image_path_base)
                temp_path.unlink(missing_ok=True)

                result["local_image"] = str(final_image_path)
                result["downloaded_image_url"] = final_url
                image_ok = True
            except Exception as exc:
                temp_path.unlink(missing_ok=True)
                notes.append(f"image:convert_error:{exc}")
        else:
            temp_path.unlink(missing_ok=True)
            notes.append(f"image:{error or 'unknown_error'}")

    if pdf_url and pdf_path is not None:
        skip_reason = _pdf_skip_reason(pdf_url)
        if skip_reason == "legacy_https_certificate":
            ok, final_url, error = _download_legacy_https_pdf(pdf_url, pdf_path)
            if ok:
                result["local_pdf"] = str(pdf_path)
                result["downloaded_pdf_url"] = final_url
                pdf_ok = True
            else:
                if pdf_path.exists():
                    pdf_path.unlink(missing_ok=True)
                notes.append(f"pdf:{error or 'unknown_error'}")
        elif skip_reason:
            pdf_skipped = True
            notes.append(f"pdf:skipped:{skip_reason}")
        elif _is_url(pdf_url):
            ok, final_url, _content_type, error = download_binary(pdf_url, pdf_path, accept_pdf=True)
            if ok:
                result["local_pdf"] = str(pdf_path)
                result["downloaded_pdf_url"] = final_url
                pdf_ok = True
            else:
                if pdf_path.exists():
                    pdf_path.unlink(missing_ok=True)
                notes.append(f"pdf:{error or 'unknown_error'}")
        else:
            ok, error = _copy_local_pdf(pdf_url, pdf_path)
            if ok:
                result["local_pdf"] = str(pdf_path)
                result["downloaded_pdf_url"] = pdf_url
                pdf_ok = True
            else:
                notes.append(f"pdf:{error}")

    if image_ok and pdf_ok:
        result["download_status"] = "downloaded_image_and_pdf"
    elif image_ok:
        result["download_status"] = "downloaded_image_only"
    elif pdf_ok:
        result["download_status"] = "downloaded_pdf_only"
    elif image_url or (pdf_url and not pdf_skipped):
        result["download_status"] = "download_failed"
    else:
        result["download_status"] = "nothing_to_download"

    result["download_notes"] = " | ".join(notes)
    return result

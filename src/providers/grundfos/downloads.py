from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

from src.core.text import clean_spaces
from src.providers.bosch.media import build_download_paths, download_binary, save_ecommerce_jpg
from src.providers.grundfos.catalog import is_excluded_document, score_document


def _is_pdf_file(path: Path) -> bool:
    try:
        return path.read_bytes()[:4] == b"%PDF"
    except OSError:
        return False


def _pick_archive_pdf_member(zip_path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(zip_path) as archive:
        pdf_members = [
            member
            for member in archive.infolist()
            if not member.is_dir() and member.filename.lower().endswith(".pdf")
        ]
        if not pdf_members:
            return "", "zip_without_pdf"

        ranked_members: list[tuple[int, zipfile.ZipInfo]] = []
        for member in pdf_members:
            file_name = Path(member.filename).name
            if is_excluded_document(title=file_name, file_name=file_name, url=file_name):
                continue

            score = score_document(
                title=file_name,
                url=file_name,
                file_name=file_name,
            )
            if score == 0:
                score = 10

            score += min(member.file_size // 50000, 25)
            ranked_members.append((score, member))

        if not ranked_members:
            return "", "zip_only_excluded_pdfs"

        ranked_members.sort(
            key=lambda item: (
                item[0],
                item[1].file_size,
                Path(item[1].filename).name.lower(),
            ),
            reverse=True,
        )
        return ranked_members[0][1].filename, ""


def _save_pdf_from_archive(zip_path: Path, pdf_path: Path) -> tuple[bool, str]:
    member_name, reason = _pick_archive_pdf_member(zip_path)
    if not member_name:
        return False, reason

    with zipfile.ZipFile(zip_path) as archive, tempfile.TemporaryDirectory() as temp_dir:
        extracted_path = Path(archive.extract(member_name, path=temp_dir))
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(extracted_path, pdf_path)
        return True, f"zip_member:{Path(member_name).name}"


def _download_image(result: dict, image_url: str, image_path_base: Path, notes: list[str]) -> bool:
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


def _download_document(result: dict, pdf_url: str, pdf_path: Path, notes: list[str]) -> bool:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_doc_path = Path(temp_dir) / "grundfos_doc.bin"
        ok, final_url, content_type, error = download_binary(pdf_url, temp_doc_path, accept_pdf=False)
        if not ok:
            notes.append(f"pdf:{error or 'unknown_error'}")
            return False

        if _is_pdf_file(temp_doc_path):
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(temp_doc_path, pdf_path)
        elif zipfile.is_zipfile(temp_doc_path):
            saved_ok, zip_note = _save_pdf_from_archive(temp_doc_path, pdf_path)
            if not saved_ok:
                notes.append(f"pdf:{zip_note}")
                return False
            notes.append(f"pdf:{zip_note}")
        else:
            notes.append(f"pdf:unexpected_content_type:{content_type or 'unknown'}")
            return False

    result["local_pdf"] = str(pdf_path)
    result["downloaded_pdf_url"] = final_url
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
        pdf_ok = _download_document(result, pdf_url, pdf_path, notes)
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

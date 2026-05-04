from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, ImageOps

from src.core.text import clean_spaces, slugify

BINARY_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

BINARY_HEADERS = {
    "User-Agent": BINARY_USER_AGENT,
    "Accept": "*/*",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

PDF_HEADERS = {
    "User-Agent": BINARY_USER_AGENT,
    "Accept": "application/pdf,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


def download_binary(url: str, destination: Path, accept_pdf: bool = False) -> tuple[bool, str, str, str]:
    try:
        req = Request(url, headers=PDF_HEADERS if accept_pdf else BINARY_HEADERS)
        with urlopen(req, timeout=45) as response:
            final_url = response.geturl()
            content_type = (response.headers.get("Content-Type") or "").lower()
            data = response.read()

        if not data:
            return False, final_url, content_type, "empty_response"

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return True, final_url, content_type, ""
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return False, url, "", f"download_error:{exc}"
    
def validate_pdf_url(url: str) -> tuple[str, str, str]:
    try:
        req = Request(url, headers=PDF_HEADERS)
        with urlopen(req, timeout=45) as response:
            final_url = response.geturl()
            content_type = (response.headers.get("Content-Type") or "").lower()

        if "pdf" in content_type:
            return "ok", final_url, content_type

        return "", final_url, content_type
    except (HTTPError, URLError, TimeoutError, OSError):
        return "", url, ""


def save_ecommerce_jpg(
    src_path: Path,
    dst_base_path: Path,
    canvas_size: tuple[int, int] = (1600, 1600),
) -> Path:
    dst_path = dst_base_path.with_suffix(".jpg")
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(src_path) as img:
        img = ImageOps.exif_transpose(img).convert("RGBA")

        white_bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(white_bg, img).convert("RGB")

        img.thumbnail(canvas_size, Image.LANCZOS)

        canvas = Image.new("RGB", canvas_size, (255, 255, 255))
        x = (canvas_size[0] - img.width) // 2
        y = (canvas_size[1] - img.height) // 2
        canvas.paste(img, (x, y))

        if dst_path.exists():
            dst_path.unlink()

        canvas.save(
            dst_path,
            "JPEG",
            quality=92,
            optimize=True,
            progressive=True,
            subsampling=0,
        )

    return dst_path

def _brand_from_dir(path: Path) -> str:
    name = slugify(path.name or "", max_length=40).replace("-", "_").upper()
    name = name.replace("_RESOLVED", "")
    name = name.replace("_IMAGES", "")
    name = name.replace("_PDFS", "")
    return name or "GENERIC"

def build_download_paths(
    reference: str,
    name: str,
    preferred_pdf_kind: str,
    preferred_pdf_url: str,
    resolved_image_url: str,
    images_dir: Path,
    pdfs_dir: Path,
) -> tuple[Path | None, Path | None]:
    brand_part = _brand_from_dir(images_dir)
    ref_part = slugify(reference, max_length=60).replace("-", "").upper()

    image_path = images_dir / f"SS12_{brand_part}_{ref_part}_IMG"
    pdf_path = pdfs_dir / f"SS12_{brand_part}_{ref_part}_FT.pdf"

    return image_path, pdf_path


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
        temp_path = image_path_base.with_suffix(".imgtmp")
        ok, final_url, content_type, error = download_binary(image_url, temp_path, accept_pdf=False)

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
        temp_pdf_path = pdf_path.with_suffix(".tmp")
        ok, final_url, content_type, error = download_binary(pdf_url, temp_pdf_path, accept_pdf=True)
        if ok:
            try:
                if temp_pdf_path.read_bytes()[:4] != b"%PDF":
                    notes.append(f"pdf:invalid_pdf_signature:{content_type or 'unknown'}")
                else:
                    pdf_path.parent.mkdir(parents=True, exist_ok=True)
                    temp_pdf_path.replace(pdf_path)
                    result["local_pdf"] = str(pdf_path)
                    result["downloaded_pdf_url"] = final_url
                    pdf_ok = True
            except OSError as exc:
                notes.append(f"pdf:write_error:{exc}")
            finally:
                temp_pdf_path.unlink(missing_ok=True)
        else:
            temp_pdf_path.unlink(missing_ok=True)
            notes.append(f"pdf:{error or 'unknown_error'}")

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

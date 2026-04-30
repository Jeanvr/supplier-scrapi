from __future__ import annotations

import re
import shutil
import statistics
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from PIL import Image, ImageDraw

from src.core.pdf_tools import extract_pdf_text, find_reference_pages, group_consecutive_pages, merge_selected_pages, pick_reference_block
from src.core.text import clean_spaces
from src.providers.bosch.media import build_download_paths, download_binary
from src.providers.simple_downloads import attach_downloads as attach_simple_downloads


_PDF_TEXT_CACHE: dict[tuple[Path, int, int], list[str]] = {}
_PRICE_HEADER_TOKENS = {
    "PRECIO",
    "PRECIO",
    "PVP",
    "EUR",
    "EUROS",
    "TARIFA",
    "PRICE",
    "PRICES",
    "LISTINO",
}
_PRICE_VALUE_RE = re.compile(r"^(?:€|EUR)?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2,4})\s*(?:€|EUR)?$", re.IGNORECASE)
_CURRENCY_RE = re.compile(r"(?:€|EUR)", re.IGNORECASE)
_PRICE_FRAGMENT_RE = re.compile(r"^\d{1,3}(?:[.,]\d{1,3}){1,3}$")
_DIGIT_TOKEN_RE = re.compile(r"^\d[\d.,]*$")
_CODE_RE = re.compile(r"\b[A-Z]{0,4}\d[A-Z0-9/-]{4,}\b")
_LINE_TOKEN_RE = re.compile(r"[A-Z0-9][A-Z0-9/-]{1,}")
_FAMILY_PRODUCT_HINTS = {
    "BOMBA",
    "BOMBAS",
    "SUBM",
    "SUBMERGIBLE",
    "SUBMERSIBLE",
    "DRENA",
    "JET",
    "CIRCULADOR",
    "CIRCULATING",
    "MULTICELULAR",
    "GRUP",
    "PRESSIO",
    "PRESSURE",
    "BOOSTING",
    "MOTOR",
    "MOTORS",
    "PUMP",
    "PUMPS",
}
_FAMILY_SKIP_HINTS = {
    "INTERRUPTOR",
    "PRESSOSTAT",
    "REGULADOR",
    "CABLE",
    "ARMARI",
    "ELECTRIC",
    "PANEL",
    "ACCESSORY",
    "ACCESSORIES",
    "ACCESSORI",
    "SONDA",
}
_FAMILY_TEXT_HINTS = {
    "APPLICATION",
    "APPLICATIONS",
    "CAMPO",
    "APLICACIONES",
    "EXECUTION",
    "CONSTRUCTION",
    "DESCRIPTION",
    "DESCRIPTIONS",
    "CARACTERISTICAS",
    "CHARACTERISTICS",
    "PERFORMANCE",
    "CURVES",
    "DATOS",
    "TECNICOS",
    "TECHNICAL",
}
_TITLE_STOPWORDS = {
    "CALPEDA",
    "CATALOGO",
    "CATALOGO",
    "CATALOGUE",
    "TARIFA",
    "PRICE",
    "LISTINO",
    "MARZO",
    "MARCH",
    "EDICION",
    "EDITION",
    "CODIGO",
    "CÓDIGO",
    "PRECIO",
    "PVP",
    "EUR",
    "EUROS",
}
_PRICE_FALLBACK_FILL = (248, 249, 243)
_CALPEDA_CACHE_DIR = Path("data/tmp/calpeda_cache")


@dataclass
class _WordBox:
    text: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float


@dataclass
class _PriceBand:
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    has_header: bool
    anchors: list[_WordBox]


def _append_note(result: dict, note: str) -> None:
    existing_notes = clean_spaces(result.get("notes", ""))
    result["notes"] = " | ".join(part for part in [existing_notes, note] if part)


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


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def _is_pdf_file(path: Path) -> bool:
    try:
        return path.read_bytes()[:4] == b"%PDF"
    except OSError:
        return False


def _cache_path_for_pdf_url(pdf_url: str) -> Path:
    parsed = urlparse(pdf_url)
    file_name = Path(unquote(parsed.path)).name or "calpeda_cached.pdf"
    return _CALPEDA_CACHE_DIR / file_name


def _resolve_cached_pdf_source(pdf_url: str, result: dict) -> tuple[Path | None, str]:
    pdf_url = clean_spaces(pdf_url)
    if not pdf_url:
        return None, ""

    if not _looks_like_url(pdf_url):
        local_source = _resolve_local_pdf(pdf_url)
        if local_source is None:
            _append_download_note(result, "pdf:cache_source_missing")
            return None, ""
        if not _is_pdf_file(local_source):
            _append_download_note(result, "pdf:cache_source_not_pdf")
            return None, ""
        _append_download_note(result, f"pdf:cache_bypass_local:{local_source}")
        return local_source, str(local_source)

    cache_path = _cache_path_for_pdf_url(pdf_url)
    if cache_path.is_file() and cache_path.stat().st_size > 0 and _is_pdf_file(cache_path):
        _append_download_note(result, f"pdf:cache_hit:{cache_path}")
        return cache_path, pdf_url

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temp_cache_path = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
    ok, final_url, content_type, error = download_binary(pdf_url, temp_cache_path, accept_pdf=True)
    if not ok:
        temp_cache_path.unlink(missing_ok=True)
        _append_download_note(result, f"pdf:cache_download_error:{error or 'unknown_error'}")
        return None, ""

    if "pdf" not in content_type and not _is_pdf_file(temp_cache_path):
        temp_cache_path.unlink(missing_ok=True)
        _append_download_note(result, f"pdf:cache_unexpected_content_type:{content_type or 'unknown'}")
        return None, ""

    if cache_path.exists():
        cache_path.unlink(missing_ok=True)
    temp_cache_path.replace(cache_path)
    _append_download_note(result, f"pdf:cache_miss_downloaded:{cache_path}")
    return cache_path, final_url or pdf_url


def _materialize_cached_pdf(result: dict, pdf_url: str, pdf_path: Path) -> bool:
    cache_source, final_url = _resolve_cached_pdf_source(pdf_url, result)
    if cache_source is None:
        return False

    try:
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        if pdf_path.exists():
            pdf_path.unlink(missing_ok=True)
        shutil.copyfile(cache_source, pdf_path)
    except OSError as exc:
        _append_download_note(result, f"pdf:cache_copy_error:{exc}")
        return False

    result["local_pdf"] = str(pdf_path)
    result["downloaded_pdf_url"] = final_url
    return True


def _pdf_pages(pdf_path: Path) -> list[str]:
    stat = pdf_path.stat()
    cache_key = (pdf_path.resolve(), stat.st_size, int(stat.st_mtime_ns))
    cached = _PDF_TEXT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    pages = extract_pdf_text(pdf_path)
    _PDF_TEXT_CACHE[cache_key] = pages
    return pages


def _pick_exact_reference_page(pdf_path: Path, reference: str) -> int | None:
    pages = _pdf_pages(pdf_path)
    reference_pages = find_reference_pages(reference, pages)
    if not reference_pages:
        return None

    return pick_reference_block(group_consecutive_pages(reference_pages))[0]


def _clean_page_lines(page_text: str, *, limit: int = 12) -> list[str]:
    lines: list[str] = []
    for raw_line in page_text.splitlines():
        line = clean_spaces(raw_line)
        if not line:
            continue
        upper = line.upper()
        if upper.startswith(("ED.", "EDICION", "EDITION")):
            continue
        if len(line) <= 2:
            continue
        lines.append(upper)
        if len(lines) >= limit:
            break
    return lines


def _line_tokens(line: str) -> set[str]:
    tokens: set[str] = set()
    for match in _LINE_TOKEN_RE.findall(line.upper()):
        token = match.strip("-/ ")
        if len(token) < 3:
            continue
        if token in _TITLE_STOPWORDS:
            continue
        if token.isdigit():
            continue
        tokens.add(token)
    return tokens


def _name_family_tokens(name: str) -> set[str]:
    tokens = _line_tokens(clean_spaces(name).upper())
    return {
        token for token in tokens
        if token not in _FAMILY_SKIP_HINTS and token not in _FAMILY_PRODUCT_HINTS
    }


def _page_title_tokens(page_text: str) -> set[str]:
    tokens: set[str] = set()
    for line in _clean_page_lines(page_text, limit=10):
        tokens.update(_line_tokens(line))
    return tokens


def _price_token_count(page_text: str) -> int:
    upper = page_text.upper()
    return upper.count("€") + upper.count("EUR") + upper.count("PRECIO") + upper.count("PVP")


def _is_table_like_page(page_text: str) -> bool:
    upper = page_text.upper()
    code_count = len(_CODE_RE.findall(upper))
    digit_lines = sum(1 for line in _clean_page_lines(page_text, limit=20) if sum(ch.isdigit() for ch in line) >= 8)
    if code_count >= 4 or digit_lines >= 4:
        return True
    if _price_token_count(page_text) >= 2:
        return True
    return False


def _is_family_crop_candidate(name: str) -> bool:
    upper = clean_spaces(name).upper()
    if any(token in upper for token in _FAMILY_SKIP_HINTS):
        return False
    return any(token in upper for token in _FAMILY_PRODUCT_HINTS)


def _family_page_score(
    page_text: str,
    current_tokens: set[str],
    name_tokens: set[str],
    *,
    distance: int,
) -> int:
    candidate_tokens = _page_title_tokens(page_text)
    overlap_current = len(candidate_tokens & current_tokens)
    overlap_name = len(candidate_tokens & name_tokens)
    score = overlap_current * 4 + overlap_name * 3

    upper = page_text.upper()
    if any(hint in upper for hint in _FAMILY_TEXT_HINTS):
        score += 4
    if not _is_table_like_page(page_text):
        score += 2
    if len(candidate_tokens) >= 2:
        score += 1

    score -= max(0, distance - 1)
    return score


def _select_pages_for_reference(
    pdf_path: Path,
    reference: str,
    name: str,
) -> tuple[list[int], bool, bool]:
    pages = _pdf_pages(pdf_path)
    reference_pages = find_reference_pages(reference, pages)
    if not reference_pages:
        return [], False, False

    target_page = pick_reference_block(group_consecutive_pages(reference_pages))[0]
    selected_pages = [target_page]
    current_text = pages[target_page - 1]
    should_evaluate = _is_family_crop_candidate(name) and _is_table_like_page(current_text)
    if not should_evaluate:
        return selected_pages, False, False

    current_tokens = _page_title_tokens(current_text)
    name_tokens = _name_family_tokens(name)
    if not current_tokens and not name_tokens:
        return selected_pages, False, True

    previous_pages: list[int] = []
    for distance, candidate_page in enumerate(range(target_page - 1, max(0, target_page - 3), -1), start=1):
        candidate_text = pages[candidate_page - 1]
        score = _family_page_score(
            candidate_text,
            current_tokens=current_tokens,
            name_tokens=name_tokens,
            distance=distance,
        )
        threshold = 5 if distance == 1 else 6
        if score < threshold:
            if distance == 1:
                break
            continue
        previous_pages.append(candidate_page)

    if not previous_pages:
        return selected_pages, False, True

    selected_pages = sorted(previous_pages) + [target_page]
    return selected_pages[:3], True, True


def _render_pdf_page_to_png(pdf_path: Path, page_number: int, output_png: Path) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    prefix = output_png.with_suffix("")
    subprocess.run(
        [
            "pdftoppm",
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            "-png",
            "-r",
            "170",
            str(pdf_path),
            str(prefix),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    generated_candidates = sorted(prefix.parent.glob(f"{prefix.name}-*.png"))
    if not generated_candidates:
        raise RuntimeError("pdftoppm_no_output")
    generated_png = generated_candidates[0]
    generated_png.replace(output_png)


def _pdf_page_count(pdf_path: Path) -> int:
    completed = subprocess.run(
        ["pdfinfo", str(pdf_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    match = re.search(r"Pages:\s+(\d+)", completed.stdout)
    if not match:
        raise RuntimeError("pdf_page_count_missing")
    return int(match.group(1))


def _bbox_page_words(pdf_path: Path, page_number: int) -> tuple[float, float, list[_WordBox]]:
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
        html_path = Path(tmp.name)

    try:
        subprocess.run(
            [
                "pdftotext",
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-bbox-layout",
                str(pdf_path),
                str(html_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        root = ET.fromstring(html_path.read_text(encoding="utf-8", errors="ignore"))
    finally:
        html_path.unlink(missing_ok=True)

    page = root.find(".//{*}page")
    if page is None:
        raise RuntimeError("bbox_page_missing")

    page_width = float(page.attrib["width"])
    page_height = float(page.attrib["height"])
    words: list[_WordBox] = []
    for word in page.iterfind(".//{*}word"):
        text = clean_spaces("".join(word.itertext()))
        if not text:
            continue
        words.append(
            _WordBox(
                text=text,
                x_min=float(word.attrib["xMin"]),
                y_min=float(word.attrib["yMin"]),
                x_max=float(word.attrib["xMax"]),
                y_max=float(word.attrib["yMax"]),
            )
        )

    return page_width, page_height, words


def _normalized_token(text: str) -> str:
    return re.sub(r"[^A-Z]", "", clean_spaces(text).upper())


def _is_price_header_word(word: _WordBox) -> bool:
    return _normalized_token(word.text) in _PRICE_HEADER_TOKENS


def _is_price_value_word(word: _WordBox) -> bool:
    normalized = clean_spaces(word.text)
    return bool(_PRICE_VALUE_RE.match(normalized)) or bool(_CURRENCY_RE.search(normalized))


def _is_price_fragment_word(word: _WordBox) -> bool:
    normalized = clean_spaces(word.text)
    if _is_price_value_word(word):
        return True
    if _PRICE_FRAGMENT_RE.match(normalized):
        return True
    return bool(_DIGIT_TOKEN_RE.match(normalized) and any(ch in normalized for ch in ",."))


def _group_price_bands(words: list[_WordBox], page_width: float) -> list[_PriceBand]:
    anchors = [
        word for word in words
        if _is_price_header_word(word)
        or _is_price_value_word(word)
        or (
            _is_price_fragment_word(word)
            and word.x_min >= page_width * 0.56
        )
    ]
    anchors.sort(key=lambda word: ((word.x_min + word.x_max) / 2, word.y_min))

    bands: list[_PriceBand] = []
    for word in anchors:
        candidate_x0 = max(0.0, word.x_min - 10.0)
        candidate_x1 = min(page_width, word.x_max + 14.0)
        attached = False
        for band in bands:
            if candidate_x0 <= band.x_max + 28.0 and candidate_x1 >= band.x_min - 28.0:
                band.x_min = min(band.x_min, candidate_x0)
                band.x_max = max(band.x_max, candidate_x1)
                band.y_min = min(band.y_min, word.y_min)
                band.y_max = max(band.y_max, word.y_max)
                band.has_header = band.has_header or _is_price_header_word(word)
                band.anchors.append(word)
                attached = True
                break
        if attached:
            continue

        bands.append(
            _PriceBand(
                x_min=candidate_x0,
                x_max=candidate_x1,
                y_min=word.y_min,
                y_max=word.y_max,
                has_header=_is_price_header_word(word),
                anchors=[word],
            )
        )

    return bands


def _collect_price_rectangles(
    words: list[_WordBox],
    page_width: float,
    page_height: float,
) -> list[tuple[float, float, float, float]]:
    bands = _group_price_bands(words, page_width)
    if not bands:
        return []

    rects: list[tuple[float, float, float, float]] = []
    for band in bands:
        x0 = max(0.0, band.x_min - 18.0)
        x1 = min(page_width, band.x_max + 24.0)
        y0 = max(0.0, band.y_min - 10.0)
        y1 = min(page_height, page_height - 18.0 if band.has_header else band.y_max + 16.0)

        band_words = [
            word for word in words
            if ((word.x_min + word.x_max) / 2) >= x0 - 8.0
            and ((word.x_min + word.x_max) / 2) <= x1 + 8.0
            and word.y_min >= y0 - 8.0
            and (
                _is_price_header_word(word)
                or _is_price_value_word(word)
                or _is_price_fragment_word(word)
            )
        ]
        if band_words:
            x0 = max(0.0, min(word.x_min for word in band_words) - 20.0)
            x1 = min(page_width, max(word.x_max for word in band_words) + 26.0)
            y0 = max(0.0, min(word.y_min for word in band_words) - 10.0)
            if band.has_header:
                y1 = min(page_height, page_height - 18.0)
            else:
                y1 = min(page_height, max(word.y_max for word in band_words) + 18.0)

        if x1 - x0 < 18.0:
            continue
        rects.append((x0, y0, x1, y1))

    merged: list[tuple[float, float, float, float]] = []
    for rect in sorted(rects):
        if not merged:
            merged.append(rect)
            continue
        prev_x0, prev_y0, prev_x1, prev_y1 = merged[-1]
        x0, y0, x1, y1 = rect
        if x0 <= prev_x1 + 16.0 and y0 <= prev_y1 + 16.0:
            merged[-1] = (
                min(prev_x0, x0),
                min(prev_y0, y0),
                max(prev_x1, x1),
                max(prev_y1, y1),
            )
            continue
        merged.append(rect)

    return merged


def _median_fill_color(samples: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    if not samples:
        return _PRICE_FALLBACK_FILL

    filtered = [
        rgb for rgb in samples
        if sum(rgb) >= 540
    ] or samples
    return tuple(int(statistics.median(channel)) for channel in zip(*filtered))


def _sample_fill_color(
    img: Image.Image,
    *,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
) -> tuple[int, int, int]:
    samples: list[tuple[int, int, int]] = []
    candidate_boxes = [
        (max(0, x0 - 14), y0, max(0, x0 - 2), y1),
        (min(img.width, x1 + 2), y0, min(img.width, x1 + 14), y1),
        (x0, max(0, y0 - 12), x1, max(0, y0 - 2)),
        (x0, min(img.height, y1 + 2), x1, min(img.height, y1 + 12)),
    ]
    for sx0, sy0, sx1, sy1 in candidate_boxes:
        if sx1 - sx0 < 2 or sy1 - sy0 < 2:
            continue
        crop = img.crop((sx0, sy0, sx1, sy1))
        samples.extend(list(crop.getdata()))
    return _median_fill_color(samples)


def _paint_rectangles_on_png(
    png_path: Path,
    *,
    page_width: float,
    page_height: float,
    rectangles: list[tuple[float, float, float, float]],
) -> bool:
    if not rectangles:
        return False

    with Image.open(png_path) as img:
        img = img.convert("RGB")
        scale_x = img.width / page_width
        scale_y = img.height / page_height
        draw = ImageDraw.Draw(img)
        for x0, y0, x1, y1 in rectangles:
            px0 = max(0, int(x0 * scale_x))
            py0 = max(0, int(y0 * scale_y))
            px1 = min(img.width, int(x1 * scale_x))
            py1 = min(img.height, int(y1 * scale_y))
            fill_color = _sample_fill_color(img, x0=px0, y0=py0, x1=px1, y1=py1)
            draw.rectangle(
                [
                    px0,
                    py0,
                    px1,
                    py1,
                ],
                fill=fill_color,
            )
        img.save(png_path, "PNG")

    return True


def _replace_pdf_with_png_pdf(png_paths: list[Path], output_pdf: Path) -> None:
    images: list[Image.Image] = []
    try:
        for png_path in png_paths:
            with Image.open(png_path) as img:
                images.append(img.convert("RGB"))
        if not images:
            raise RuntimeError("missing_png_pages")
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        images[0].save(
            output_pdf,
            "PDF",
            resolution=170.0,
            save_all=True,
            append_images=images[1:],
        )
    finally:
        for img in images:
            img.close()


def _update_download_status_after_pdf_drop(result: dict) -> None:
    has_image = bool(clean_spaces(result.get("local_image", "")))
    has_pdf = bool(clean_spaces(result.get("local_pdf", "")))
    image_url = clean_spaces(result.get("resolved_image_url", ""))
    pdf_url = clean_spaces(result.get("preferred_pdf_url", ""))

    if has_image and has_pdf:
        result["download_status"] = "downloaded_image_and_pdf"
    elif has_image and (image_url or pdf_url):
        result["download_status"] = "downloaded_image_only"
    elif has_pdf:
        result["download_status"] = "downloaded_pdf_only"
    elif image_url or pdf_url:
        result["download_status"] = "download_failed"
    else:
        result["download_status"] = "nothing_to_download"


def _trim_and_redact_pdf(result: dict, reference: str) -> None:
    output_pdf = _resolve_local_pdf(clean_spaces(result.get("local_pdf", "")))
    if output_pdf is None:
        _append_note(result, "calpeda_pdf_trim_missing_local_pdf")
        return

    try:
        selected_pages, family_crop_applied, family_crop_evaluated = _select_pages_for_reference(
            output_pdf,
            reference,
            clean_spaces(result.get("name", "")),
        )
    except Exception as exc:
        _append_note(result, f"calpeda_pdf_trim_error:{exc}")
        return

    if not selected_pages:
        output_pdf.unlink(missing_ok=True)
        result["local_pdf"] = ""
        result["downloaded_pdf_url"] = ""
        _update_download_status_after_pdf_drop(result)
        _append_note(result, "calpeda_pdf_ref_not_exact")
        return

    _append_note(result, "calpeda_tarifa_ref_exact")
    if family_crop_applied:
        _append_note(result, "calpeda_family_crop")
        _append_note(result, f"calpeda_family_pages={','.join(str(page) for page in selected_pages)}")
    elif family_crop_evaluated:
        _append_note(result, "calpeda_family_crop_skipped")

    temp_trimmed_pdf = output_pdf.with_suffix(".trim.tmp.pdf")
    temp_pngs: list[Path] = []
    try:
        merge_selected_pages(output_pdf, selected_pages, temp_trimmed_pdf)
        page_count = _pdf_page_count(temp_trimmed_pdf)
        any_price_removed = False
        for page_number in range(1, page_count + 1):
            page_width, page_height, words = _bbox_page_words(temp_trimmed_pdf, page_number)
            rectangles = _collect_price_rectangles(words, page_width, page_height)
            temp_png = output_pdf.with_suffix(f".trim.{page_number}.tmp.png")
            temp_pngs.append(temp_png)
            _render_pdf_page_to_png(temp_trimmed_pdf, page_number, temp_png)
            if _paint_rectangles_on_png(
                temp_png,
                page_width=page_width,
                page_height=page_height,
                rectangles=rectangles,
            ):
                any_price_removed = True

        if any_price_removed:
            _append_note(result, "price_removed")

        _replace_pdf_with_png_pdf(temp_pngs, output_pdf)
    except Exception as exc:
        _append_note(result, f"calpeda_pdf_trim_error:{exc}")
    finally:
        temp_trimmed_pdf.unlink(missing_ok=True)
        for temp_png in temp_pngs:
            temp_png.unlink(missing_ok=True)


def attach_downloads(
    result: dict,
    reference: str,
    name: str,
    download_enabled: bool,
    images_dir: Path,
    pdfs_dir: Path,
) -> dict:
    preferred_pdf_url = clean_spaces(result.get("preferred_pdf_url", ""))
    image_only_result = dict(result)
    image_only_result["preferred_pdf_url"] = ""
    image_only_result["fallback_pdf_url"] = ""

    result = attach_simple_downloads(
        result=image_only_result,
        reference=reference,
        name=name,
        download_enabled=download_enabled,
        images_dir=images_dir,
        pdfs_dir=pdfs_dir,
    )
    result["preferred_pdf_url"] = preferred_pdf_url

    if not download_enabled:
        return result

    reference = clean_spaces(reference)
    if preferred_pdf_url:
        _image_path_base, pdf_path = build_download_paths(
            reference=reference,
            name=name,
            preferred_pdf_kind=clean_spaces(result.get("preferred_pdf_kind", "")),
            preferred_pdf_url=preferred_pdf_url,
            resolved_image_url=clean_spaces(result.get("resolved_image_url", "")),
            images_dir=images_dir,
            pdfs_dir=pdfs_dir,
        )
        if pdf_path is not None:
            pdf_ok = _materialize_cached_pdf(result, preferred_pdf_url, pdf_path)
            if not pdf_ok and pdf_path.exists():
                pdf_path.unlink(missing_ok=True)
            _update_download_status_after_pdf_drop(result)

    if reference and clean_spaces(result.get("local_pdf", "")):
        _trim_and_redact_pdf(result, reference)

    return result

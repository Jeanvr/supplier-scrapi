from __future__ import annotations
from src.core.text import (
    normalize_text as core_normalize_text,
    normalize_search_text as core_normalize_search_text,
    clean_spaces as core_clean_spaces,
    slugify as core_slugify,
    build_name_tokens as core_build_name_tokens,
)
from src.providers.bosch.config import (
    DOCS_BASE,
    DOCS_SEARCH_URL,
    DOCS_PORTAL_DOC_TYPES,
    MEDIA_PREFIX,
    DEFAULT_IMAGES_DIR,
    DEFAULT_PDFS_DIR,
)
import argparse
import ast
import json
import mimetypes
import re
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen
from PIL import Image, ImageOps

import pandas as pd
from parsel import Selector

HTML_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

BINARY_HEADERS = {
    "User-Agent": HTML_HEADERS["User-Agent"],
    "Accept": "*/*",
    "Accept-Language": HTML_HEADERS["Accept-Language"],
}

PDF_HEADERS = {
    "User-Agent": HTML_HEADERS["User-Agent"],
    "Accept": "application/pdf,*/*;q=0.8",
    "Accept-Language": HTML_HEADERS["Accept-Language"],
}

REF_ALIASES = [
    "referencia",
    "ref",
    "artpro",
    "supplier_ref",
    "codigo",
    "código",
    "codart",
]

NAME_ALIASES = [
    "nombre",
    "descripcion",
    "descripción",
    "description",
    "product_name",
    "articulo",
    "artículo",
]

STOPWORDS = {
    "bosch",
    "junkers",
    "caldera",
    "calentador",
    "calentadores",
    "termo",
    "termos",
    "electrico",
    "eléctrico",
    "electric",
    "agua",
    "gas",
    "natural",
    "nat",
    "vertical",
    "horizontal",
    "toma",
    "superior",
    "inferior",
    "condensacion",
    "condensación",
    "mural",
    "de",
    "del",
    "la",
    "el",
    "los",
    "las",
    "y",
    "con",
    "para",
    "por",
    "en",
    "no",
    "nox",
    "bajo",
    "baix",
    "baja",
    "alto",
    "w",
    "kw",
    "mm",
    "l",
}
IMAGE_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def normalize_text(value: object) -> str:
    return core_normalize_text(value)

def normalize_search_text(value: object) -> str:
    return core_normalize_search_text(value)


def clean_spaces(value: object) -> str:
    return core_clean_spaces(value)


def slugify(value: object, max_length: int = 80) -> str:
    return core_slugify(value, max_length=max_length)


def pick_column(df: pd.DataFrame, aliases: list[str], required: bool = True) -> str | None:
    normalized_map = {normalize_text(col): col for col in df.columns}
    for alias in aliases:
        col = normalized_map.get(normalize_text(alias))
        if col:
            return col
    if required:
        raise ValueError(
            f"No encuentro columna válida. Probadas: {aliases}. "
            f"Columnas reales: {list(df.columns)}"
        )
    return None


def fetch_url(url: str, headers: dict[str, str]) -> tuple[str, str, str]:
    req = Request(url, headers=headers)
    with urlopen(req, timeout=30) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        content_type = (response.headers.get("Content-Type") or "").lower()
        return text, response.geturl(), content_type


def validate_pdf_url(pdf_url: str) -> tuple[bool, str, str]:
    try:
        req = Request(pdf_url, headers=PDF_HEADERS)
        with urlopen(req, timeout=30) as response:
            final_url = response.geturl()
            content_type = (response.headers.get("Content-Type") or "").lower()
            ok = "pdf" in content_type or final_url.lower().endswith(".pdf")
            return ok, final_url, content_type
    except (HTTPError, URLError, TimeoutError) as exc:
        return False, pdf_url, f"error:{exc}"


def build_name_tokens(name: str) -> list[str]:
    return core_build_name_tokens(name)

def first_non_empty(row: dict, keys: list[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue

        if isinstance(value, list):
            for item in value:
                item = clean_spaces(item)
                if item:
                    return item
            continue

        text = clean_spaces(value)
        if not text:
            continue

        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, list):
                    for item in parsed:
                        item = clean_spaces(item)
                        if item:
                            return item
            except Exception:
                pass

        return text

    return ""


def load_catalog_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []

    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            title = first_non_empty(
                row,
                ["nombre", "name", "title", "product_name", "product_title", "display_name"],
            )
            reference = first_non_empty(
                row,
                ["referencia", "reference", "order_number", "supplier_ref", "artpro", "codart"],
            )
            page_url = first_non_empty(
                row,
                ["product_url", "detail_url", "source_url", "url", "docs_url"],
            )
            docs_url = first_non_empty(
                row,
                ["docs_url"],
            )
            image_url = first_non_empty(
                row,
                ["image_url", "primary_image_url", "local_image", "images", "image_urls"],
            )
            pdf_url = first_non_empty(
                row,
                ["pdf_url", "tech_pdf_url", "file_urls"],
            )

            row["_title"] = title
            row["_reference"] = reference
            row["_page_url"] = page_url
            row["_docs_url"] = docs_url
            row["_image_url"] = image_url
            row["_pdf_url"] = pdf_url
            row["_search_blob"] = normalize_search_text(
                f"{title} {reference} {page_url} {docs_url}"
            )

            rows.append(row)

    return rows


def score_catalog_row(reference: str, name: str, row: dict) -> int:
    ref_norm = normalize_text(reference)
    name_norm = normalize_search_text(name)
    row_title = normalize_search_text(row.get("_title", ""))
    row_ref = normalize_text(row.get("_reference", ""))
    row_blob = row.get("_search_blob", "")

    score = 0

    if ref_norm and row_ref and ref_norm == row_ref:
        score += 3000

    if ref_norm and ref_norm in row_blob:
        score += 900

    query_tokens = set(build_name_tokens(name))
    row_tokens = set(build_name_tokens(row.get("_title", "")))
    score += len(query_tokens & row_tokens) * 90

    if name_norm and row_title:
        ratio = SequenceMatcher(None, name_norm, row_title).ratio()
        score += int(ratio * 400)

    for token in ["therm", "tronic", "6600", "2000", "sr", "vertical"]:
        if token in name_norm and token in row_title:
            score += 60

    if row.get("_page_url"):
        score += 20
    if row.get("_image_url"):
        score += 20
    if row.get("_pdf_url"):
        score += 10

    return score


def find_best_catalog_row(reference: str, name: str, catalog_rows: list[dict]) -> tuple[dict | None, int]:
    best_row = None
    best_score = -1

    for row in catalog_rows:
        score = score_catalog_row(reference, name, row)
        if score > best_score:
            best_score = score
            best_row = row

    if best_row is None:
        return None, -1

    if best_score < 220:
        return None, best_score

    return best_row, best_score


def extract_best_image(selector: Selector, base_url: str) -> str:
    candidates: list[tuple[int, str]] = []

    def push(url: str, score: int) -> None:
        url = clean_spaces(url)
        if not url:
            return

        absolute = urljoin(base_url, url)
        norm = normalize_text(absolute)

        if any(bad in norm for bad in ["logo", "icon", "sprite", "social", "erp", "label", "placeholder"]):
            return

        if not re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", absolute, re.IGNORECASE):
            score -= 40

        if "ocsmedia" in norm or "product" in norm:
            score += 80

        candidates.append((score, absolute))

    og_image = selector.xpath('//meta[@property="og:image"]/@content').get("")
    if og_image:
        push(og_image, 400)

    twitter_image = selector.xpath('//meta[@name="twitter:image"]/@content').get("")
    if twitter_image:
        push(twitter_image, 350)

    for img in selector.xpath("//img"):
        for attr_name in ["src", "data-src", "data-lazy-src", "data-image", "data-zoom-image"]:
            value = img.attrib.get(attr_name, "")
            if value:
                push(value, 180)

    if not candidates:
        return ""

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def extract_page_title(selector: Selector) -> str:
    for xp in [
        '//meta[@property="og:title"]/@content',
        "//title/text()",
        "//h1/text()",
    ]:
        value = clean_spaces(selector.xpath(xp).get(""))
        if value:
            return value
    return ""


def extract_page_links(selector: Selector, base_url: str) -> list[dict]:
    links: list[dict] = []
    seen: set[str] = set()

    for a in selector.xpath("//a[@href]"):
        href = clean_spaces(a.attrib.get("href", ""))
        if not href:
            continue

        absolute = urljoin(base_url, href)
        if absolute in seen:
            continue
        seen.add(absolute)

        label = clean_spaces(" ".join(a.xpath(".//text()").getall()))
        links.append(
            {
                "label": label,
                "href": absolute,
            }
        )

    return links


def score_page_pdf(link: dict) -> tuple[int, str]:
    label_norm = normalize_text(link.get("label", ""))
    href_norm = normalize_text(link.get("href", ""))

    score = -1000
    kind = ""

    if ".pdf" not in href_norm and "download" not in label_norm and "ocsmedia" not in href_norm:
        return score, kind

    if "ficha tecnica" in label_norm or "ficha-tecnica" in href_norm or "ficha_tecnica" in href_norm:
        score = 1000
        kind = "ficha_tecnica"
    elif "catalogo" in label_norm or "catalogo" in href_norm:
        score = 760
        kind = "catalogo_producto"
    elif "ficha del producto" in label_norm:
        score = 120
        kind = "ficha_producto_erp"
    elif "etiqueta" in label_norm or "/label/" in href_norm:
        score = -600
        kind = "etiqueta_erp"
    elif ".pdf" in href_norm:
        score = 40
        kind = "pdf_generico"

    if "b5-web-product-data-service.azurewebsites.net/pdf/" in href_norm:
        score -= 350
    if "b5-web-product-data-service.azurewebsites.net/label/" in href_norm:
        score -= 700
    if "ocsmedia" in href_norm:
        score += 120
    if link.get("href", "").lower().endswith(".pdf"):
        score += 30

    return score, kind


def resolve_from_product_page(page_url: str, catalog_image_url: str = "") -> dict:
    try:
        html, final_url, _ = fetch_url(page_url, HTML_HEADERS)
    except Exception as exc:
        return {
            "page_ok": False,
            "product_page_url": page_url,
            "product_page_title": "",
            "resolved_image_url": catalog_image_url,
            "preferred_pdf_kind": "",
            "preferred_pdf_label": "",
            "preferred_pdf_url": "",
            "page_notes": f"page_error:{exc}",
        }

    selector = Selector(text=html)
    title = extract_page_title(selector)
    image_url = catalog_image_url or extract_best_image(selector, final_url)
    links = extract_page_links(selector, final_url)

    scored_links: list[dict] = []
    for link in links:
        score, kind = score_page_pdf(link)
        if kind:
            link["score"] = score
            link["kind"] = kind
            scored_links.append(link)

    scored_links.sort(key=lambda x: x["score"], reverse=True)

    preferred = None
    for link in scored_links:
        if link["kind"] in {"ficha_tecnica", "catalogo_producto"} and link["score"] > 0:
            preferred = link
            break

    if preferred is None:
        for link in scored_links:
            if link["score"] > 0:
                preferred = link
                break

    return {
        "page_ok": True,
        "product_page_url": final_url,
        "product_page_title": title,
        "resolved_image_url": image_url,
        "preferred_pdf_kind": preferred.get("kind", "") if preferred else "",
        "preferred_pdf_label": preferred.get("label", "") if preferred else "",
        "preferred_pdf_url": preferred.get("href", "") if preferred else "",
        "page_notes": "",
    }


def detect_docs_portal_type(text: str) -> str:
    norm = normalize_text(text)
    for doc_type in DOCS_PORTAL_DOC_TYPES:
        if doc_type in norm:
            return doc_type
    if "catalogo" in norm:
        return "catalogo"
    return ""


def choose_context_text(link_sel) -> str:
    candidates = []
    for xp in [
        'ancestor::*[self::li][1]',
        'ancestor::*[self::article][1]',
        'ancestor::*[self::div][1]',
        'ancestor::*[self::div][2]',
        'ancestor::*[self::div][3]',
    ]:
        node = link_sel.xpath(xp)
        if node:
            text = clean_spaces(" ".join(node.xpath(".//text()").getall()))
            if text:
                candidates.append(text)

    if not candidates:
        return clean_spaces(" ".join(link_sel.xpath(".//text()").getall()))

    candidates = sorted(set(candidates), key=len)
    for text in candidates:
        if len(text) >= 20:
            return text
    return candidates[0]


def parse_docs_portal_results(html: str) -> list[dict]:
    selector = Selector(text=html)
    seen: set[str] = set()
    rows: list[dict] = []

    for link in selector.xpath('//a[contains(@href, "/download/pdf/file/")]'):
        href = clean_spaces(link.attrib.get("href", ""))
        if not href:
            continue

        pdf_url = urljoin(DOCS_BASE, href)
        if pdf_url in seen:
            continue
        seen.add(pdf_url)

        title = clean_spaces(" ".join(link.xpath(".//text()").getall()))
        context_text = choose_context_text(link)
        merged_text = clean_spaces(f"{title} | {context_text}")
        doc_type = detect_docs_portal_type(merged_text)

        rows.append(
            {
                "title": title or context_text[:180],
                "doc_type": doc_type,
                "pdf_url": pdf_url,
                "context_text": context_text,
            }
        )

    return rows


def score_docs_portal_candidate(candidate: dict, reference: str, name: str) -> int:
    merged = normalize_search_text(
        f"{candidate.get('title', '')} {candidate.get('doc_type', '')} {candidate.get('context_text', '')}"
    )
    ref_norm = normalize_text(reference)
    score = 0

    doc_type = normalize_text(candidate.get("doc_type", ""))
    if doc_type == "tabla datos de producto":
        score += 1000
    elif doc_type == "ficha tecnica":
        score += 950
    elif doc_type == "ficha de producto":
        score += 300
    elif doc_type == "catalogo":
        score += 260
    elif doc_type == "hoja de datos de energia":
        score += 120
    elif doc_type == "manual de instalacion":
        score += 60
    elif doc_type == "instrucciones de uso":
        score += 40
    elif doc_type == "suplemento":
        score -= 800
    elif doc_type == "catalogo de piezas de repuesto":
        score -= 900

    if ref_norm and ref_norm in merged:
        score += 180

    for token in build_name_tokens(name):
        if token in merged:
            score += 20

    if "accesorios" in merged:
        score -= 700
    if "repuesto" in merged or "repuestos" in merged:
        score -= 900

    return score


def resolve_from_docs_portal(reference: str, name: str) -> dict:
    queries = []
    ref = clean_spaces(reference)
    name_q = normalize_search_text(name)

    if ref:
        queries.append(ref)
    if ref and name_q:
        queries.append(f"{ref} {name_q}")

    best = None
    notes = []

    for query in queries:
        search_url = DOCS_SEARCH_URL.format(query=quote(query))
        try:
            html, final_url, _ = fetch_url(search_url, HTML_HEADERS)
        except Exception as exc:
            notes.append(f"docs_search_error:{exc}")
            continue

        candidates = parse_docs_portal_results(html)
        for cand in candidates:
            cand["score"] = score_docs_portal_candidate(cand, reference, name)
            cand["search_url"] = final_url
            if best is None or cand["score"] > best["score"]:
                best = cand

    if best is None:
        return {
            "fallback_doc_type": "",
            "fallback_title": "",
            "fallback_pdf_url": "",
            "fallback_notes": " | ".join(notes) if notes else "sin resultados docs portal",
        }

    return {
        "fallback_doc_type": best.get("doc_type", ""),
        "fallback_title": best.get("title", ""),
        "fallback_pdf_url": best.get("pdf_url", ""),
        "fallback_notes": " | ".join(notes),
    }


def guess_extension(url: str, content_type: str, default_ext: str) -> str:
    url_path = urlparse(url).path.lower()

    for ext in [".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        if url_path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext

    content_type = (content_type or "").split(";")[0].strip().lower()
    if content_type == "application/pdf":
        return ".pdf"
    if content_type in IMAGE_EXT_BY_CONTENT_TYPE:
        return IMAGE_EXT_BY_CONTENT_TYPE[content_type]

    guessed = mimetypes.guess_extension(content_type) if content_type else None
    return guessed or default_ext


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


def save_ecommerce_jpg(src_path: Path, dst_base_path: Path, canvas_size: tuple[int, int] = (1600, 1600)) -> Path:
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


def build_download_paths(
    reference: str,
    name: str,
    preferred_pdf_kind: str,
    preferred_pdf_url: str,
    resolved_image_url: str,
    images_dir: Path,
    pdfs_dir: Path,
) -> tuple[Path | None, Path | None]:
    ref_part = slugify(reference, max_length=40).replace("-", "")

    image_path = None
    pdf_path = None
    image_path = images_dir / f"{MEDIA_PREFIX}_{ref_part}_IMG"
    pdf_path = pdfs_dir / f"{MEDIA_PREFIX}_{ref_part}_FT.pdf"
    
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
        ok, final_url, content_type, error = download_binary(pdf_url, pdf_path, accept_pdf=True)
        if ok:
            result["local_pdf"] = str(pdf_path)
            result["downloaded_pdf_url"] = final_url
            pdf_ok = True
        else:
            if pdf_path.exists():
                pdf_path.unlink(missing_ok=True)
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


def resolve_reference(reference: str, name: str, catalog_rows: list[dict]) -> dict:
    matched_row, matched_score = find_best_catalog_row(reference, name, catalog_rows)

    product_page_url = ""
    product_page_title = ""
    matched_catalog_name = ""
    matched_catalog_ref = ""
    matched_catalog_score = matched_score if matched_row else ""
    resolved_image_url = ""
    preferred_pdf_kind = ""
    preferred_pdf_label = ""
    preferred_pdf_url = ""
    notes: list[str] = []

    if matched_row is not None:
        matched_catalog_name = clean_spaces(matched_row.get("_title", ""))
        matched_catalog_ref = clean_spaces(matched_row.get("_reference", ""))
        candidate_page_url = clean_spaces(matched_row.get("_page_url", ""))
        candidate_image_url = clean_spaces(matched_row.get("_image_url", ""))

        if candidate_page_url:
            page_result = resolve_from_product_page(candidate_page_url, candidate_image_url)
            product_page_url = page_result.get("product_page_url", "")
            product_page_title = page_result.get("product_page_title", "")
            resolved_image_url = page_result.get("resolved_image_url", "")
            preferred_pdf_kind = page_result.get("preferred_pdf_kind", "")
            preferred_pdf_label = page_result.get("preferred_pdf_label", "")
            preferred_pdf_url = page_result.get("preferred_pdf_url", "")
            if page_result.get("page_notes"):
                notes.append(page_result["page_notes"])
        else:
            resolved_image_url = candidate_image_url
            notes.append("catalog_match_sin_page_url")
    else:
        notes.append("sin_match_fuerte_en_bosch_catalog")

    docs_fallback = resolve_from_docs_portal(reference, name)

    pdf_check_ok = ""
    pdf_content_type = ""
    if preferred_pdf_url:
        ok, final_pdf_url, content_type = validate_pdf_url(preferred_pdf_url)
        preferred_pdf_url = final_pdf_url
        pdf_check_ok = ok
        pdf_content_type = content_type

    status = "not_found"
    if preferred_pdf_kind == "ficha_tecnica" and preferred_pdf_url:
        status = "resolved_ficha_tecnica"
    elif preferred_pdf_kind == "catalogo_producto" and preferred_pdf_url:
        status = "resolved_catalogo_producto"
    elif resolved_image_url:
        status = "resolved_image_only"

    return {
        "resolver_status": status,
        "reference": reference,
        "name": name,
        "matched_catalog_name": matched_catalog_name,
        "matched_catalog_ref": matched_catalog_ref,
        "matched_catalog_score": matched_catalog_score,
        "product_page_url": product_page_url,
        "product_page_title": product_page_title,
        "resolved_image_url": resolved_image_url,
        "preferred_pdf_kind": preferred_pdf_kind,
        "preferred_pdf_label": preferred_pdf_label,
        "preferred_pdf_url": preferred_pdf_url,
        "preferred_pdf_check_ok": pdf_check_ok,
        "preferred_pdf_content_type": pdf_content_type,
        "preferred_doc_type": preferred_pdf_kind,
        "preferred_title": preferred_pdf_label,
        "fallback_doc_type": docs_fallback.get("fallback_doc_type", ""),
        "fallback_title": docs_fallback.get("fallback_title", ""),
        "fallback_pdf_url": docs_fallback.get("fallback_pdf_url", ""),
        "notes": " | ".join([n for n in notes if n]),
    }
def bosch_family_key(name: str) -> str:
    raw = clean_spaces(name).upper()
    if not raw:
        return ""

    raw = re.sub(r"\b(BOSCH|JUNKERS)\b", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()

    model_match = re.search(r"\b([A-Z]{1,8}\d{3,4}[A-Z]{0,3})\b", raw)
    model = model_match.group(1) if model_match else ""

    orientation = ""
    if "VERTICAL" in raw:
        orientation = "VERTICAL"
    elif "HORIZONTAL" in raw:
        orientation = "HORIZONTAL"

    cleaned = re.sub(r"\b\d{2,4}\s*[A-Z]\b", " ", raw)
    cleaned = re.sub(r"\b\d{2,4}\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    parts = []
    if model:
        parts.append(model)
    if orientation:
        parts.append(orientation)
    if cleaned:
        parts.append(cleaned)

    return " | ".join(parts)


def promote_family_tech_sheets(results: list[dict]) -> list[dict]:
    family_tech_map: dict[str, dict] = {}

    for result in results:
        if result.get("resolver_status") != "resolved_ficha_tecnica":
            continue

        family_key = bosch_family_key(
            result.get("name", "") or result.get("matched_catalog_name", "")
        )
        pdf_url = clean_spaces(result.get("preferred_pdf_url", ""))

        if not family_key or not pdf_url:
            continue

        if family_key not in family_tech_map:
            family_tech_map[family_key] = {
                "preferred_pdf_url": pdf_url,
                "preferred_pdf_kind": "ficha_tecnica",
                "preferred_pdf_label": clean_spaces(result.get("preferred_pdf_label", "")),
                "preferred_pdf_check_ok": result.get("preferred_pdf_check_ok", ""),
                "preferred_pdf_content_type": result.get("preferred_pdf_content_type", ""),
                "source_reference": result.get("reference", ""),
            }

    for result in results:
        if result.get("resolver_status") != "resolved_catalogo_producto":
            continue

        family_key = bosch_family_key(
            result.get("name", "") or result.get("matched_catalog_name", "")
        )
        inherited = family_tech_map.get(family_key)

        if not inherited:
            continue

        result["preferred_pdf_url"] = inherited["preferred_pdf_url"]
        result["preferred_pdf_kind"] = "ficha_tecnica"
        result["preferred_doc_type"] = "ficha_tecnica"
        result["preferred_pdf_label"] = inherited["preferred_pdf_label"] or result.get("preferred_pdf_label", "")
        result["preferred_title"] = result["preferred_pdf_label"]
        result["preferred_pdf_check_ok"] = inherited["preferred_pdf_check_ok"]
        result["preferred_pdf_content_type"] = inherited["preferred_pdf_content_type"]
        result["resolver_status"] = "resolved_ficha_tecnica"

        inherited_note = f"family_tech_inherited_from:{inherited['source_reference']}"
        existing_notes = clean_spaces(result.get("notes", ""))
        result["notes"] = " | ".join([x for x in [existing_notes, inherited_note] if x])

    return results

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolver Bosch: imagen + ficha técnica/catálogo desde Bosch Home Comfort, con docs portal como fallback."
    )
    parser.add_argument("--excel", required=True, help="Ruta del Excel de entrada")
    parser.add_argument("--out", required=True, help="Ruta del Excel de salida")
    parser.add_argument(
        "--catalog-jsonl",
        default=DEFAULT_IMAGES_DIR,
        help="Ruta del catálogo JSONL Bosch ya scrapeado",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Descarga imagen y PDF resueltos a disco",
    )
    parser.add_argument(
        "--images-dir",
        default="data/output/images/bosch_resolved",
        help="Carpeta de descarga de imágenes resueltas",
    )
    parser.add_argument(
        "--pdfs-dir",
        default=DEFAULT_PDFS_DIR,
        help="Carpeta de descarga de PDFs resueltos",
    )
    return parser
def run_bosch_doc_resolver(
    *,
    excel: str,
    out: str,
    catalog_jsonl: str = "data/output/bosch_catalog.jsonl",
    download: bool = False,
    images_dir: str = DEFAULT_IMAGES_DIR,
    pdfs_dir: str = DEFAULT_PDFS_DIR,
) -> None:
    excel_path = Path(excel)
    out_path = Path(out)
    catalog_path = Path(catalog_jsonl)
    images_dir_path = Path(images_dir)
    pdfs_dir_path = Path(pdfs_dir)

    if not excel_path.exists():
        raise FileNotFoundError(f"No existe el Excel: {excel_path}")

    df = pd.read_excel(excel_path, dtype=str).fillna("")
    ref_col = pick_column(df, REF_ALIASES, required=True)
    name_col = pick_column(df, NAME_ALIASES, required=False)

    catalog_rows = load_catalog_rows(catalog_path)
    print(f"bosch_catalog_rows: {len(catalog_rows)} | catalog_path: {catalog_path}")

    results = []
    total = len(df)

    for idx, row in df.iterrows():
        reference = clean_spaces(row.get(ref_col, ""))
        name = clean_spaces(row.get(name_col, "")) if name_col else ""

        if not reference:
            result = {
                "resolver_status": "skipped_empty_reference",
                "reference": "",
                "name": name,
                "matched_catalog_name": "",
                "matched_catalog_ref": "",
                "matched_catalog_score": "",
                "product_page_url": "",
                "product_page_title": "",
                "resolved_image_url": "",
                "preferred_pdf_kind": "",
                "preferred_pdf_label": "",
                "preferred_pdf_url": "",
                "preferred_pdf_check_ok": "",
                "preferred_pdf_content_type": "",
                "preferred_doc_type": "",
                "preferred_title": "",
                "fallback_doc_type": "",
                "fallback_title": "",
                "fallback_pdf_url": "",
                "notes": "fila sin referencia",
            }
        else:
            print(f"[{idx + 1}/{total}] Resolviendo {reference} | {name}")
            result = resolve_reference(reference, name, catalog_rows)
            print(
                f"  -> provisional {result['resolver_status']} | "
                f"img={'si' if result['resolved_image_url'] else 'no'} | "
                f"pdf={result['preferred_pdf_kind'] or '-'}"
            )

        results.append(result)

    results = promote_family_tech_sheets(results)

    final_results = []
    for result in results:
        result = attach_downloads(
            result=result,
            reference=clean_spaces(result.get("reference", "")),
            name=clean_spaces(result.get("name", "")),
            download_enabled=download,
            images_dir=images_dir_path,
            pdfs_dir=pdfs_dir_path,
        )

        if result.get("reference"):
            print(
                f"  => final {result['reference']} | "
                f"{result['resolver_status']} | "
                f"pdf={result['preferred_pdf_kind'] or '-'} | "
                f"download={result['download_status']}"
            )

        final_results.append(result)

    results = final_results

    result_df = pd.DataFrame(results)

    output_df = df.copy()
    for col in result_df.columns:
        if col in {"reference", "name"}:
            continue
        output_df[col] = result_df[col]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    output_df.to_excel(out_path, index=False)

    print("\nResumen")
    print(f"  total_rows: {len(output_df)}")
    print(f"  resolved_ficha_tecnica: {(output_df['resolver_status'] == 'resolved_ficha_tecnica').sum()}")
    print(f"  resolved_catalogo_producto: {(output_df['resolver_status'] == 'resolved_catalogo_producto').sum()}")
    print(f"  resolved_image_only: {(output_df['resolver_status'] == 'resolved_image_only').sum()}")
    print(f"  not_found: {(output_df['resolver_status'] == 'not_found').sum()}")
    if "download_status" in output_df.columns:
        print(f"  downloaded_image_and_pdf: {(output_df['download_status'] == 'downloaded_image_and_pdf').sum()}")
        print(f"  downloaded_image_only: {(output_df['download_status'] == 'downloaded_image_only').sum()}")
    print(f"  output: {out_path}")
    if download:
        print(f"  pdfs_dir: {pdfs_dir_path}")


def main() -> None:
    args = build_parser().parse_args()
    run_bosch_doc_resolver(
        excel=args.excel,
        out=args.out,
        catalog_jsonl=args.catalog_jsonl,
        download=args.download,
        images_dir=args.images_dir,
        pdfs_dir=args.pdfs_dir,
    )


if __name__ == "__main__":
    main()
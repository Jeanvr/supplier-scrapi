from __future__ import annotations

import hashlib
from pathlib import Path

from src.core.pdf_tools import extract_pdf_text, find_reference_pages
from src.core.text import clean_spaces
from src.providers.calpeda.catalog import _extract_pdf_urls, _fetch_text
from src.providers.bosch.media import download_binary


PDF_SUPPORT_CACHE_DIR = Path("/tmp/calpeda_pdf_support_cache")
CHECKABLE_STATUSES = {"resolved_ficha_tecnica", "resolved_catalogo_producto"}


def _empty_pdf_support() -> dict:
    return {
        "sku_exact_supported_by_pdf": "",
        "pdf_reference_pages": "",
        "pdf_support_reason": "",
    }


def _candidate_pdf_url(result: dict) -> tuple[str, str]:
    preferred_pdf_url = clean_spaces(result.get("preferred_pdf_url", ""))
    if preferred_pdf_url:
        return preferred_pdf_url, "preferred_pdf"

    fallback_pdf_url = clean_spaces(result.get("fallback_pdf_url", ""))
    if fallback_pdf_url:
        return fallback_pdf_url, "fallback_pdf"

    return "", ""


def _score_b19_pdf_url(pdf_url: str) -> int:
    low = clean_spaces(pdf_url).lower()
    score = 0

    if "/cataloghi_pdf/" in low:
        score += 80
    if "catalogue" in low or "catalogo" in low:
        score += 40
    if "50hz" in low or "50%20hz" in low:
        score += 35
    if "/en%20-%20english_new/" in low or "/en%20-%20english/" in low:
        score += 25

    if "datasheet" in low or "/singoli_" in low:
        score -= 200
    if "60hz" in low or "60%20hz" in low:
        score -= 120
    if "/istruzioni" in low or "instruction" in low:
        score -= 120
    if "spare%20parts" in low or "crosssections" in low or "cross-sections" in low:
        score -= 120
    if "brochure" in low or "ecodesign" in low or "company" in low or "/ie_" in low:
        score -= 120
    if "/it%20-%20italiano/" in low or "/it%20-%20italian/" in low:
        score -= 80

    return score


def _pick_b19_pdf_url(pdf_urls: list[str]) -> str:
    if not pdf_urls:
        return ""

    best_url = max(pdf_urls, key=_score_b19_pdf_url)
    if _score_b19_pdf_url(best_url) < 80:
        return ""

    return best_url


def _find_b19_pdf_url(product_page_url: str, page_cache: dict[str, str], b19_url_cache: dict[str, str]) -> tuple[str, str]:
    product_page_url = clean_spaces(product_page_url)
    if not product_page_url:
        return "", "missing_product_page_url"

    if product_page_url in b19_url_cache:
        cached_url = b19_url_cache[product_page_url]
        return cached_url, "cache_hit" if cached_url else "missing_catalog_pdf"

    try:
        html = page_cache.get(product_page_url)
        if html is None:
            html = _fetch_text(product_page_url)
            page_cache[product_page_url] = html
    except Exception as exc:
        return "", f"page_fetch_error:{exc.__class__.__name__}"

    pdf_urls = _extract_pdf_urls(html)
    b19_pdf_url = _pick_b19_pdf_url(pdf_urls)
    b19_url_cache[product_page_url] = b19_pdf_url
    if not b19_pdf_url:
        return "", "missing_catalog_pdf"

    return b19_pdf_url, "catalog_found"


def _cache_path_for_url(pdf_url: str) -> Path:
    digest = hashlib.sha1(pdf_url.encode("utf-8")).hexdigest()
    return PDF_SUPPORT_CACHE_DIR / f"{digest}.pdf"


def _ensure_cached_pdf(pdf_url: str) -> tuple[Path | None, str]:
    if not pdf_url:
        return None, "missing_pdf_url"

    cache_path = _cache_path_for_url(pdf_url)
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path, "cache_hit"

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    ok, _final_url, content_type, error = download_binary(pdf_url, cache_path, accept_pdf=True)
    if not ok:
        cache_path.unlink(missing_ok=True)
        return None, error or "download_failed"

    if content_type and "pdf" not in content_type:
        cache_path.unlink(missing_ok=True)
        return None, f"unexpected_content_type:{content_type}"

    return cache_path, "downloaded"


def _check_pdf_support(
    reference: str,
    pdf_path: Path,
    pages_cache: dict[Path, list[str]],
) -> tuple[str, str, str]:
    try:
        pages = pages_cache.get(pdf_path)
        if pages is None:
            pages = extract_pdf_text(pdf_path)
            pages_cache[pdf_path] = pages
    except Exception as exc:
        return "", "", f"pdf_extract_error:{exc.__class__.__name__}"

    reference_pages = find_reference_pages(reference, pages)
    if reference_pages:
        return "yes", ",".join(str(page) for page in reference_pages), "reference_found"

    return "no", "", "reference_not_found"


def annotate_pdf_support(results: list[dict]) -> list[dict]:
    pages_cache: dict[Path, list[str]] = {}
    cached_pdf_paths: dict[str, tuple[Path | None, str]] = {}
    page_cache: dict[str, str] = {}
    b19_url_cache: dict[str, str] = {}

    for result in results:
        result.update(_empty_pdf_support())

        resolver_status = clean_spaces(result.get("resolver_status", ""))
        if resolver_status not in CHECKABLE_STATUSES:
            continue

        if clean_spaces(result.get("match_ref_exact", "")) == "yes":
            continue

        reference = clean_spaces(result.get("reference", ""))
        if not reference:
            continue

        pdf_url, pdf_source = _candidate_pdf_url(result)
        if not pdf_url:
            result["pdf_support_reason"] = "missing_pdf_url"
            continue

        if pdf_url not in cached_pdf_paths:
            cached_pdf_paths[pdf_url] = _ensure_cached_pdf(pdf_url)

        pdf_path, cache_reason = cached_pdf_paths[pdf_url]
        if pdf_path is None:
            result["pdf_support_reason"] = f"{pdf_source}:{cache_reason}"
            continue

        support, reference_pages, support_reason = _check_pdf_support(reference, pdf_path, pages_cache)
        if support == "yes":
            result["sku_exact_supported_by_pdf"] = support
            result["pdf_reference_pages"] = reference_pages
            result["pdf_support_reason"] = f"{pdf_source}:{support_reason}"
            continue

        reasons = [f"{pdf_source}:{support_reason}"]

        b19_pdf_url, b19_lookup_reason = _find_b19_pdf_url(
            product_page_url=result.get("product_page_url", ""),
            page_cache=page_cache,
            b19_url_cache=b19_url_cache,
        )
        if not b19_pdf_url:
            result["sku_exact_supported_by_pdf"] = support
            result["pdf_reference_pages"] = reference_pages
            reasons.append(f"b19:{b19_lookup_reason}")
            result["pdf_support_reason"] = "|".join(reasons)
            continue

        if b19_pdf_url not in cached_pdf_paths:
            cached_pdf_paths[b19_pdf_url] = _ensure_cached_pdf(b19_pdf_url)

        b19_pdf_path, b19_cache_reason = cached_pdf_paths[b19_pdf_url]
        if b19_pdf_path is None:
            result["sku_exact_supported_by_pdf"] = support
            result["pdf_reference_pages"] = reference_pages
            reasons.append(f"b19:{b19_cache_reason}")
            result["pdf_support_reason"] = "|".join(reasons)
            continue

        support, reference_pages, support_reason = _check_pdf_support(reference, b19_pdf_path, pages_cache)
        result["sku_exact_supported_by_pdf"] = support
        result["pdf_reference_pages"] = reference_pages
        reasons.append(f"b19:{support_reason}")
        result["pdf_support_reason"] = "|".join(reasons)

    return results

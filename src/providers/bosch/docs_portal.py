from __future__ import annotations

from urllib.parse import quote, urljoin

from parsel import Selector

from src.core.text import (
    build_name_tokens,
    clean_spaces,
    normalize_search_text,
    normalize_text,
)
from src.providers.bosch.config import DOCS_BASE, DOCS_PORTAL_DOC_TYPES


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
def resolve_from_docs_portal(
    reference: str,
    name: str,
    *,
    search_url_template: str,
    fetch_html,
    html_headers: dict[str, str],
) -> dict:
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
        search_url = search_url_template.format(query=quote(query))
        try:
            html, final_url, _ = fetch_html(search_url, html_headers)
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
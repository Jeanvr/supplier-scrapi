from __future__ import annotations

import re
from urllib.parse import urljoin

from parsel import Selector

from src.core.text import clean_spaces, normalize_text


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


def resolve_from_product_page(
    page_url: str,
    catalog_image_url: str = "",
    *,
    fetch_html,
    html_headers: dict[str, str],
) -> dict:
    try:
        html, final_url, _ = fetch_html(page_url, html_headers)
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
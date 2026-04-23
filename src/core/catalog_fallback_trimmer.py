from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from src.core.pdf_tools.pdf_operations import (
    extract_pdf_text,
    find_reference_pages,
    group_consecutive_pages,
    merge_selected_pages,
)
from src.core.text import clean_spaces, slugify


CATALOG_PAGE_THRESHOLD = 20
MAX_REFERENCE_PAGES = 2
TRIM_ENABLED_PROVIDERS = {"tucaisa", "genebresa"}
MODEL_TOKEN_RE = re.compile(r"\b[A-Z]{1,5}-\d{2,5}[A-Z]?\b")
PRODUCT_CONTEXT_WORDS = {
    "APLICACIONES",
    "MODELO",
    "RACORERIA",
    "RACORERÍA",
    "PRESION",
    "PRESIÓN",
    "PRESION/TEMP",
    "PRESIÓN/TEMP",
    "CAUDAL",
    "MATERIALES",
}
BAD_PAGE_MARKERS = {
    "LISTA DE CODIGOS",
    "LISTA DE CÓDIGOS",
    "ACCESORIOS VALVULAS",
    "ACCESORIOS VÁLVULAS",
}
COMMON_NAME_TOKENS = {
    "TMM",
    "TUCAI",
    "VALVULA",
    "VÁLVULA",
    "BOLA",
    "AMB",
    "ANTI",
    "ANTICAL",
    "CAL",
    "RETENCIO",
    "RETENCIÓ",
    "AIXETA",
    "RAPID",
    "RAPID",
    "BLAU",
    "VERMELL",
    "MANETA",
    "POTES",
}


def _normalize_text(text: str) -> str:
    text = clean_spaces(text).upper()
    text = text.replace("Á", "A").replace("É", "E").replace("Í", "I")
    text = text.replace("Ó", "O").replace("Ú", "U").replace("Ç", "C")
    return re.sub(r"\s+", " ", text).strip()


def _strong_model_tokens(*values: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for value in values:
        for match in MODEL_TOKEN_RE.findall(_normalize_text(value)):
            if match not in seen:
                seen.add(match)
                tokens.append(match)
    return tokens


def _name_tokens(name: str) -> set[str]:
    tokens: set[str] = set()
    for token in re.findall(r"[A-Z0-9]+", _normalize_text(name)):
        if token in COMMON_NAME_TOKENS or len(token) < 3:
            continue
        tokens.add(token)
    return tokens


def _is_bad_page(page_text: str) -> bool:
    page_norm = _normalize_text(page_text)
    return any(marker in page_norm for marker in BAD_PAGE_MARKERS)


def _page_score(page_text: str, *, model_token: str, name_tokens: set[str]) -> int:
    page_norm = _normalize_text(page_text)
    if model_token not in page_norm or _is_bad_page(page_text):
        return -1000

    model_counts = {
        token: page_norm.count(token)
        for token in set(MODEL_TOKEN_RE.findall(page_norm))
    }
    model_count = model_counts.get(model_token, 0)
    if any(count > model_count for token, count in model_counts.items() if token != model_token):
        return -1000

    score = 20
    first_model_pos = page_norm.find(model_token)
    if 0 <= first_model_pos <= 1200:
        score += 12

    for word in PRODUCT_CONTEXT_WORDS:
        if word in page_norm:
            score += 4

    score += len(name_tokens & set(re.findall(r"[A-Z0-9]+", page_norm))) * 2

    if "MODELO" in page_norm and ("RACORERIA" in page_norm or "RACORERÍA" in page_norm):
        score += 8

    return score


def _choose_reference_pages(
    pages: list[str],
    *,
    reference: str,
    code: str,
    name: str,
    matched_name: str,
) -> tuple[list[int], str]:
    for exact_value in (reference, code):
        exact_pages = find_reference_pages(clean_spaces(exact_value), pages)
        if exact_pages:
            block = group_consecutive_pages(exact_pages)[0]
            return block[:MAX_REFERENCE_PAGES], clean_spaces(exact_value)

    name_for_tokens = matched_name or name
    name_tokens = _name_tokens(name_for_tokens)
    for model_token in _strong_model_tokens(name_for_tokens, name):
        model_pages = find_reference_pages(model_token, pages)
        scored_pages = [
            (page_number, _page_score(pages[page_number - 1], model_token=model_token, name_tokens=name_tokens))
            for page_number in model_pages
        ]
        good_pages = [page for page, score in scored_pages if score >= 36]
        if not good_pages:
            continue

        blocks = group_consecutive_pages(good_pages)
        blocks.sort(key=lambda block: (-sum(_page_score(pages[p - 1], model_token=model_token, name_tokens=name_tokens) for p in block), len(block), block[0]))
        return blocks[0][:MAX_REFERENCE_PAGES], model_token

    return [], ""


def _trimmed_pdf_path(source_pdf: Path, provider_key: str, code: str, reference: str) -> Path:
    brand = slugify(provider_key, max_length=60).replace("-", "_").upper()
    code_part = slugify(code or reference, max_length=80).replace("-", "").upper()
    return source_pdf.parent / f"SS12_{brand}_{code_part}_FT.pdf"


def _append_note(notes: str, note: str) -> str:
    notes = clean_spaces(notes)
    if not notes:
        return note
    if note in notes:
        return notes
    return f"{notes} | {note}"


def trim_catalog_fallbacks_in_excel(excel_path: Path, *, provider_key: str | None = None) -> int:
    if not excel_path.exists():
        return 0

    workbook = pd.read_excel(excel_path, sheet_name=None, dtype=str)
    if not workbook:
        return 0

    sheet_name = "results" if "results" in workbook else next(iter(workbook))
    df = workbook[sheet_name].fillna("")
    if df.empty or "resolver_status" not in df.columns or "local_pdf" not in df.columns:
        return 0

    pages_cache: dict[Path, list[str]] = {}
    trimmed_count = 0

    for idx, row in df.iterrows():
        row_provider = clean_spaces(row.get("batch_provider", "")) or clean_spaces(provider_key or "")
        if row_provider not in TRIM_ENABLED_PROVIDERS:
            continue
        if row.get("resolver_status") != "resolved_catalogo_producto":
            continue
        if row.get("preferred_pdf_kind") != "catalogo_producto":
            continue
        if "pdf:trimmed_catalog" in clean_spaces(row.get("download_notes", "")):
            continue

        source_pdf = Path(clean_spaces(row.get("local_pdf", "")))
        if not source_pdf.exists():
            continue

        try:
            pages = pages_cache.get(source_pdf)
            if pages is None:
                pages = extract_pdf_text(source_pdf)
                pages_cache[source_pdf] = pages
        except Exception:
            continue

        if len(pages) <= CATALOG_PAGE_THRESHOLD:
            continue

        reference_pages, matched_token = _choose_reference_pages(
            pages,
            reference=clean_spaces(row.get("referencia", "")),
            code=clean_spaces(row.get("codigo", "")),
            name=clean_spaces(row.get("nombre", "")),
            matched_name=clean_spaces(row.get("matched_catalog_name", "")),
        )
        if not reference_pages:
            continue

        final_pages = [1]
        for page in reference_pages:
            if page not in final_pages:
                final_pages.append(page)

        output_pdf = _trimmed_pdf_path(
            source_pdf,
            row_provider,
            clean_spaces(row.get("codigo", "")),
            clean_spaces(row.get("referencia", "")),
        )
        try:
            merge_selected_pages(source_pdf, final_pages, output_pdf)
        except Exception:
            continue

        df.at[idx, "local_pdf"] = str(output_pdf)
        trim_note = f"pdf:trimmed_catalog:{matched_token}:pages={','.join(str(page) for page in final_pages)}:source_pages={len(pages)}"
        if "download_notes" in df.columns:
            df.at[idx, "download_notes"] = _append_note(clean_spaces(row.get("download_notes", "")), trim_note)
        trimmed_count += 1

    if trimmed_count:
        workbook[sheet_name] = df
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            for name, sheet_df in workbook.items():
                sheet_df.to_excel(writer, sheet_name=name, index=False)

    return trimmed_count

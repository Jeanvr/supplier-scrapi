from __future__ import annotations

import os
import re
import unicodedata
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
GENEBRE_MODEL_TOKEN_RE = re.compile(r"\b\d{4}[A-Z]?\b")
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
GENEBRE_COMMON_NAME_TOKENS = {"GE", "GENEBRE", "GENEBRESA"}
GENEBRE_CONTEXT_STOPWORDS = {
    "ARTICLE",
    "ARTICULO",
    "BOX",
    "CAJA",
    "CARTON",
    "CODIGO",
    "CODE",
    "GE",
    "GENEBRE",
    "GENEBRESA",
    "INFORMACION",
    "INFORMATION",
    "MEDIDA",
    "NEW",
    "PAGINA",
    "PAGE",
    "PESO",
    "PRICE",
    "REF",
    "SERIE",
    "SIZE",
    "TECHNICAL",
    "TECNICA",
    "WEIGHT",
}


def _normalize_text(text: str) -> str:
    text = clean_spaces(text).upper()
    text = text.replace("Á", "A").replace("É", "E").replace("Í", "I")
    text = text.replace("Ó", "O").replace("Ú", "U").replace("Ç", "C")
    return re.sub(r"\s+", " ", text).strip()


def _normalize_ascii_text(text: str) -> str:
    text = clean_spaces(text).upper()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


def _genebre_context_root(token: str) -> str:
    if not token or token in GENEBRE_CONTEXT_STOPWORDS:
        return ""
    if token.startswith("DN") and any(ch.isdigit() for ch in token[2:]):
        return "DN"
    if token.startswith("VALVUL") or token == "VALVE":
        return "VALVULA"
    if token.startswith("ESFER") or token.startswith("BOLA") or token == "BALL":
        return "BOLA"
    if token.startswith("FILTR") or token == "FILTER":
        return "FILTRO"
    if token.startswith("RETENC") or token == "CHECK":
        return "RETENCION"
    if token.startswith("BRID") or token == "FLANGED":
        return "BRIDAS"
    if token.startswith("FUNDIC") or token == "CAST":
        return "FUNDICION"
    if token.startswith("PAPALLON") or token.startswith("MARIP") or token.startswith("BUTTERFL"):
        return "PAPALLONA"
    if token.startswith("ROSC") or token.startswith("THREAD"):
        return "ROSCA"
    if token.startswith("VIA") or token.startswith("VIE"):
        return "VIAS"
    if token.startswith("CLAPET"):
        return "CLAPETA"
    if token.startswith("PRESS") or token.startswith("PRESI"):
        return "PRESION"
    if token.startswith("REDUCT"):
        return "REDUCTORA"
    if token.startswith("COMPORT"):
        return "COMPORTA"
    if token.startswith("MANIG") or token.startswith("MANGUIT") or token.startswith("COMPENS"):
        return "MANIGUET"
    if token.startswith("ELAST"):
        return "ELASTICO"
    if token.startswith("LATON") or token.startswith("LLAUT") or token == "BRASS":
        return "LATON"
    if token.startswith("INOX") or token == "STAINLESS":
        return "INOX"
    if token.startswith("RINOX"):
        return "RINOX"
    if token in {"DOBLE", "SIMPLE", "ONDA", "WAFER", "LUG", "DISC", "GOMA", "MINI"}:
        return token
    if len(token) >= 6:
        return token[:5]
    if len(token) >= 4:
        return token
    return ""


def _genebre_context_roots(text: str) -> set[str]:
    roots: set[str] = set()
    for token in re.findall(r"[A-Z0-9]+", _normalize_ascii_text(text)):
        if token.isdigit():
            continue
        root = _genebre_context_root(token)
        if root:
            roots.add(root)
    return roots


def _is_genebre_index_page(page_text: str) -> bool:
    page_ascii = _normalize_ascii_text(page_text)
    if "INDICE" in page_ascii:
        return True
    if ("ARTICLE N" in page_ascii and "PAGE N" in page_ascii) or ("ARTICULO N" in page_ascii and "PAGINA N" in page_ascii):
        return True
    return False


def _model_tokens(text: str, *, provider_key: str = "") -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    patterns = [MODEL_TOKEN_RE]
    if provider_key == "genebresa":
        patterns.append(GENEBRE_MODEL_TOKEN_RE)

    normalized = _normalize_text(text)
    for pattern in patterns:
        for match in pattern.findall(normalized):
            if match in seen:
                continue
            seen.add(match)
            tokens.append(match)
    return tokens


def _strong_model_tokens(*values: str, provider_key: str = "") -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for value in values:
        for match in _model_tokens(value, provider_key=provider_key):
            if match not in seen:
                seen.add(match)
                tokens.append(match)
    return tokens


def _name_tokens(name: str, *, provider_key: str = "") -> set[str]:
    tokens: set[str] = set()
    common_tokens = COMMON_NAME_TOKENS
    if provider_key == "genebresa":
        common_tokens = GENEBRE_COMMON_NAME_TOKENS

    for token in re.findall(r"[A-Z0-9]+", _normalize_text(name)):
        if token in common_tokens:
            continue
        if provider_key == "genebresa":
            if token.isdigit() or len(token) < 3:
                continue
        elif len(token) < 3:
            continue
        tokens.add(token)
    return tokens


def _is_bad_page(page_text: str) -> bool:
    page_norm = _normalize_text(page_text)
    return any(marker in page_norm for marker in BAD_PAGE_MARKERS)


def _page_score(
    page_text: str,
    *,
    model_token: str,
    name_tokens: set[str],
    provider_key: str = "",
    context_roots: set[str] | None = None,
) -> int:
    page_norm = _normalize_text(page_text)
    if model_token not in page_norm or _is_bad_page(page_text):
        return -1000

    if provider_key == "genebresa":
        page_ascii = _normalize_ascii_text(page_text)
        if _is_genebre_index_page(page_text):
            return -1000

        page_roots = _genebre_context_roots(page_text)
        matched_roots = (context_roots or set()) & page_roots
        if not matched_roots:
            return -1000

        score = 20
        first_model_pos = page_ascii.find(model_token)
        if 0 <= first_model_pos <= 1500:
            score += 10

        if re.search(rf"REF\.\s+[A-Z0-9\s\-]*\b{re.escape(model_token)}\b", page_ascii):
            score += 12

        if "INFORMACION TECNICA" in page_ascii or "TECHNICAL INFORMATION" in page_ascii:
            score += 6

        score += len(matched_roots) * 8
        return score

    page_tokens = set(re.findall(r"[A-Z0-9]+", page_norm))
    model_counts = {
        token: page_norm.count(token)
        for token in set(_model_tokens(page_norm, provider_key=provider_key))
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

    matched_name_tokens = name_tokens & page_tokens
    if provider_key == "genebresa" and GENEBRE_MODEL_TOKEN_RE.fullmatch(model_token) and len(matched_name_tokens) < 2:
        return -1000

    score += len(matched_name_tokens) * 2

    if "MODELO" in page_norm and ("RACORERIA" in page_norm or "RACORERÍA" in page_norm):
        score += 8

    return score


def _choose_reference_pages(
    pages: list[str],
    *,
    provider_key: str,
    reference: str,
    code: str,
    name: str,
    matched_name: str,
    debug_trace: dict | None = None,
) -> tuple[list[int], str]:
    if debug_trace is not None:
        debug_trace["model_tokens"] = []

    for exact_value in (reference, code):
        exact_pages = find_reference_pages(clean_spaces(exact_value), pages)
        if exact_pages:
            if debug_trace is not None:
                debug_trace["exact_match"] = {
                    "value": clean_spaces(exact_value),
                    "pages": exact_pages[:10],
                }
            block = group_consecutive_pages(exact_pages)[0]
            return block[:MAX_REFERENCE_PAGES], clean_spaces(exact_value)

    name_for_tokens = matched_name or name
    name_tokens = _name_tokens(name_for_tokens, provider_key=provider_key)
    context_roots = _genebre_context_roots(f"{name_for_tokens} {name}") if provider_key == "genebresa" else set()
    for model_token in _strong_model_tokens(name_for_tokens, name, provider_key=provider_key):
        model_pages = find_reference_pages(model_token, pages)
        scored_pages = [
            (
                page_number,
                _page_score(
                    pages[page_number - 1],
                    model_token=model_token,
                    name_tokens=name_tokens,
                    provider_key=provider_key,
                    context_roots=context_roots,
                ),
            )
            for page_number in model_pages
        ]
        good_pages = [page for page, score in scored_pages if score >= 36]
        if debug_trace is not None:
            debug_trace["model_tokens"].append(
                {
                    "token": model_token,
                    "pages": model_pages[:10],
                    "max_score": max((score for _page, score in scored_pages), default=None),
                    "good_pages": good_pages[:10],
                }
            )
        if not good_pages:
            continue

        if provider_key == "genebresa":
            ranked_pages = sorted(
                ((page, score) for page, score in scored_pages if score >= 36),
                key=lambda item: (-item[1], item[0]),
            )
            if not ranked_pages:
                continue

            best_page, best_score = ranked_pages[0]
            runner_up = next((score for page, score in ranked_pages[1:] if abs(page - best_page) > 1), None)
            if runner_up is not None and best_score - runner_up < 6:
                continue

            final_pages = [best_page]
            adjacent_pages = [
                page
                for page, score in ranked_pages[1:]
                if abs(page - best_page) == 1 and score >= best_score - 8
            ]
            if adjacent_pages:
                final_pages.append(sorted(adjacent_pages, key=lambda page: abs(page - best_page))[0])
            return sorted(final_pages)[:MAX_REFERENCE_PAGES], model_token

        blocks = group_consecutive_pages(good_pages)
        blocks.sort(
            key=lambda block: (
                -sum(
                    _page_score(
                        pages[p - 1],
                        model_token=model_token,
                        name_tokens=name_tokens,
                        provider_key=provider_key,
                        context_roots=context_roots,
                    )
                    for p in block
                ),
                len(block),
                block[0],
            )
        )
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

    debug_enabled = clean_spaces(os.getenv("CATALOG_TRIM_DEBUG", "")).lower() in {"1", "true", "yes", "on"}
    skip_counts = {
        "provider_not_enabled": 0,
        "resolver_status_mismatch": 0,
        "preferred_pdf_kind_mismatch": 0,
        "already_trimmed": 0,
        "local_pdf_missing": 0,
        "extract_pdf_text_failed": 0,
        "page_threshold_not_met": 0,
        "no_reference_pages": 0,
        "merge_selected_pages_failed": 0,
    }
    debug_samples = {
        "extract_pdf_text_failed": "",
        "merge_selected_pages_failed": "",
    }
    genebre_debug_rows: list[dict] = []
    pages_cache: dict[Path, list[str]] = {}
    trimmed_count = 0

    for idx, row in df.iterrows():
        row_provider = clean_spaces(row.get("batch_provider", "")) or clean_spaces(provider_key or "")
        if row_provider not in TRIM_ENABLED_PROVIDERS:
            skip_counts["provider_not_enabled"] += 1
            continue
        if row.get("resolver_status") != "resolved_catalogo_producto":
            skip_counts["resolver_status_mismatch"] += 1
            continue
        if row.get("preferred_pdf_kind") != "catalogo_producto":
            skip_counts["preferred_pdf_kind_mismatch"] += 1
            continue
        if "pdf:trimmed_catalog" in clean_spaces(row.get("download_notes", "")):
            skip_counts["already_trimmed"] += 1
            continue

        source_pdf = Path(clean_spaces(row.get("local_pdf", "")))
        if not source_pdf.exists():
            skip_counts["local_pdf_missing"] += 1
            continue

        try:
            pages = pages_cache.get(source_pdf)
            if pages is None:
                pages = extract_pdf_text(source_pdf)
                pages_cache[source_pdf] = pages
        except Exception as exc:
            skip_counts["extract_pdf_text_failed"] += 1
            if debug_enabled and not debug_samples["extract_pdf_text_failed"]:
                debug_samples["extract_pdf_text_failed"] = f"{type(exc).__name__}: {exc}"
            continue

        if len(pages) <= CATALOG_PAGE_THRESHOLD:
            skip_counts["page_threshold_not_met"] += 1
            continue

        debug_trace = {} if debug_enabled and row_provider == "genebresa" and len(genebre_debug_rows) < 8 else None
        reference_pages, matched_token = _choose_reference_pages(
            pages,
            provider_key=row_provider,
            reference=clean_spaces(row.get("referencia", "")),
            code=clean_spaces(row.get("codigo", "")),
            name=clean_spaces(row.get("nombre", "")),
            matched_name=clean_spaces(row.get("matched_catalog_name", "")),
            debug_trace=debug_trace,
        )
        if debug_trace is not None:
            genebre_debug_rows.append(
                {
                    "nombre": clean_spaces(row.get("nombre", "")),
                    "matched_catalog_name": clean_spaces(row.get("matched_catalog_name", "")),
                    "model_tokens": debug_trace.get("model_tokens", []),
                    "selected_pages": reference_pages,
                    "matched_token": matched_token,
                }
            )
        if not reference_pages:
            skip_counts["no_reference_pages"] += 1
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
        except Exception as exc:
            skip_counts["merge_selected_pages_failed"] += 1
            if debug_enabled and not debug_samples["merge_selected_pages_failed"]:
                debug_samples["merge_selected_pages_failed"] = f"{type(exc).__name__}: {exc}"
            continue

        df.at[idx, "local_pdf"] = str(output_pdf)
        trim_note = f"pdf:trimmed_catalog:{matched_token}:pages={','.join(str(page) for page in final_pages)}:source_pages={len(pages)}"
        if "download_notes" in df.columns:
            df.at[idx, "download_notes"] = _append_note(clean_spaces(row.get("download_notes", "")), trim_note)
        trimmed_count += 1

    if debug_enabled:
        print("  catalog_trim_debug:")
        print(f"    total_rows: {len(df)}")
        print(f"    trimmed_count: {trimmed_count}")
        for key, value in skip_counts.items():
            print(f"    {key}: {value}")
        for key, value in debug_samples.items():
            if value:
                print(f"    {key}_sample: {value}")
        if genebre_debug_rows:
            print("    genebre_samples:")
            for idx, sample in enumerate(genebre_debug_rows[:5], start=1):
                print(f"      [{idx}] nombre: {sample['nombre']}")
                print(f"          matched_catalog_name: {sample['matched_catalog_name']}")
                for token_info in sample["model_tokens"][:5]:
                    print(
                        "          "
                        f"token={token_info['token']} "
                        f"pages={token_info['pages']} "
                        f"max_score={token_info['max_score']} "
                        f"good_pages={token_info['good_pages']}"
                    )
                print(
                    "          "
                    f"selected_token={sample['matched_token'] or '<none>'} "
                    f"selected_pages={sample['selected_pages']}"
                )

    if trimmed_count:
        workbook[sheet_name] = df
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            for name, sheet_df in workbook.items():
                sheet_df.to_excel(writer, sheet_name=name, index=False)

    return trimmed_count

from __future__ import annotations

import re
import unicodedata

from src.core.text import clean_spaces


STOPWORDS = {
    "CALPEDA",
    "BOMBA",
    "BOMBES",
    "SUBM",
    "SUBMERGIBLE",
    "SUBMERGIBLES",
    "SUBMERSIBLE",
    "MOTOR",
    "MOTORS",
    "GRUP",
    "PRESSIO",
    "PRESSION",
    "REGULADOR",
    "INTERRUPTOR",
    "NIVELL",
    "NIVEL",
    "CABLE",
    "ARMARI",
    "ELECTRIC",
    "ELECTRICA",
    "ELECTRICO",
    "AIGUA",
    "BRUTA",
    "NETA",
    "TRIF",
    "MONOF",
    "SENSE",
    "AMB",
    "VARIADOR",
    "INTEGRAT",
    "ESTACIO",
    "BOMBEIG",
    "CV",
    "CON",
    "SIN",
    "WITH",
    "WITHOUT",
    "AND",
    "THE",
}

CALPEDA_TARIFA_GLOBAL_URL = "https://www.calpeda.com/wp-content/uploads/2025/03/CALPEDA-Catalogo-Tarifa-B19-marzo-2025-WEB.pdf"

MANUAL_STRICT_REVIEW_REFERENCES = {
    "E70U90100000",
    "E70T91210000",
    "E70U91050000",
    "E70U91100000",
    "E70U91150000",
    "E70U91200000",
    "E70U91250000",
}
MANUAL_IMAGE_NO_CORRESPONDE_REFERENCE = "E70U90100000"
MANUAL_ACCESSORY_REFERENCE = "EEAK53120000"
MANUAL_PMAT_REFERENCES = {
    "E17028260000",
    "E17028270000",
    "E17028290000",
}
MANUAL_PMAT_PDF_URL = "https://www.calpeda.com/wp-content/uploads/2024/02/PMAT_2020.pdf"


def _fix_mojibake(text: str) -> str:
    text = clean_spaces(text)
    if not text:
        return ""
    if "Ã" in text or "Â" in text:
        try:
            return text.encode("latin-1").decode("utf-8")
        except Exception:
            return text
    return text


def _normalize(text: str) -> str:
    text = _fix_mojibake(text)
    text = clean_spaces(text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _compact(text: str) -> str:
    return _normalize(text).replace(" ", "")


def _tokens(text: str) -> list[str]:
    out = []
    for token in _normalize(text).split():
        if token in STOPWORDS:
            continue
        if len(token) >= 3 or any(ch.isdigit() for ch in token):
            out.append(token)
    return out


def _has_extended_family_variant(query_tokens: set[str], matched_tokens: set[str]) -> bool:
    for query_token in query_tokens:
        if len(query_token) < 4 or not query_token.isalpha():
            continue
        for matched_token in matched_tokens:
            if len(matched_token) < 3 or len(matched_token) >= len(query_token):
                continue
            if not matched_token.isalpha():
                continue
            if query_token.startswith(matched_token) and len(query_token) - len(matched_token) <= 2:
                return True
    return False


def _query_hints(reference: str, name: str) -> str:
    raw = f"{reference} {name}"
    norm = _normalize(raw)
    compact = norm.replace(" ", "")

    hints: list[str] = []

    if "META" in norm or "MÈTA" in _fix_mojibake(raw).upper():
        hints.append("META")

    if "MXPM" in compact or re.search(r"\bMXP\b", norm):
        hints.extend(["MXP", "E MXP"])

    if re.search(r"\bNM\b", norm) or re.search(r"\bNMD\b", norm):
        hints.extend(["NM", "NMD"])

    if "V75K" in compact or "V 75K" in norm:
        hints.extend(["V", "V75K", "V 75K"])

    if "V100K" in compact or "V 100K" in norm:
        hints.extend(["V", "V100K", "V 100K"])

    if "4CSR" in compact or "4CS R" in norm:
        hints.extend(["4CSR", "4CS R", "4CS"])

    if "4FK" in compact or "FRANKLIN" in norm:
        hints.extend(["4FK", "FRANKLIN"])

    if "PMAT" in norm:
        hints.append("PMAT")

    if "AKO" in norm:
        hints.append("AKO")

    return " ".join(hints)


def _search_blob(row: dict) -> str:
    parts = [
        row.get("supplier_ref", ""),
        row.get("name", ""),
        row.get("search_text", ""),
    ]
    return _normalize(" ".join(str(part) for part in parts if part))

def _score_row(reference: str, name: str, row: dict) -> int:
    score = 0

    query_hints = _query_hints(reference, name)
    query_text = f"{reference} {name} {query_hints}".strip()

    name_norm = _normalize(query_text)
    name_compact = _compact(query_text)
    ref_norm = _normalize(reference)
    ref_compact = _compact(reference)

    blob = _search_blob(row)
    blob_compact = blob.replace(" ", "")

    row_name = _normalize(row.get("name", ""))
    row_ref = _normalize(row.get("supplier_ref", ""))

    name_tokens = set(_tokens(query_text))
    blob_tokens = set(_tokens(blob))
    overlap = name_tokens & blob_tokens

    score += len(overlap) * 18

    if row_name and f" {row_name} " in f" {name_norm} ":
        score += 140

    row_name_compact = row_name.replace(" ", "")
    if row_name_compact and len(row_name_compact) >= 3 and row_name_compact in name_compact:
        score += 120

    if row_ref and f" {row_ref} " in f" {name_norm} ":
        score += 110

    row_ref_compact = row_ref.replace(" ", "")
    if row_ref_compact and len(row_ref_compact) >= 3 and row_ref_compact in name_compact:
        score += 95

    if ref_norm and row_ref and ref_norm == row_ref:
        score += 220

    if ref_compact and row_ref_compact and ref_compact == row_ref_compact:
        score += 200

    strong_hits = 0
    for token in name_tokens:
        if len(token) >= 3 and token in blob_tokens:
            strong_hits += 1
    score += strong_hits * 12

    if blob_compact and name_compact and row_name_compact and row_name_compact in name_compact:
        score += 80

    if row.get("image_url"):
        score += 3
    if row.get("pdf_url"):
        score += 2

    return score


def _rank_catalog_rows(reference: str, name: str, catalog_rows: list[dict]) -> list[tuple[int, dict]]:
    ranked: list[tuple[int, dict]] = []
    for row in catalog_rows:
        ranked.append((_score_row(reference, name, row), row))

    ranked.sort(
        key=lambda item: (
            item[0],
            1 if clean_spaces(item[1].get("pdf_url", "")) else 0,
            _pdf_url_language_rank(item[1].get("pdf_url", "")),
            1 if clean_spaces(item[1].get("image_url", "")) else 0,
        ),
        reverse=True,
    )
    return ranked


def _pdf_url_language_rank(pdf_url: str) -> int:
    low = clean_spaces(pdf_url).lower()

    spanish_markers = [
        "/es%20-%20spanish/",
        "/es%20-%20espanol/",
        "/es%20-%20español/",
        "/es%20-%20espa%c3%b1ol/",
        "/spanish/",
        "/espanol/",
        "/español/",
    ]
    english_markers = [
        "/en%20-%20english_new/",
        "/en%20-%20english/",
        "/english_new/",
        "/english/",
    ]

    for marker in spanish_markers:
        if marker in low:
            return 2

    for marker in english_markers:
        if marker in low:
            return 1

    return 0


def _is_official_calpeda_pdf_url(pdf_url: str) -> bool:
    low = clean_spaces(pdf_url).lower()
    return bool(low and "calpeda.com" in low)


def _is_tariff_catalog_pdf_url(pdf_url: str) -> bool:
    low = clean_spaces(pdf_url).lower()
    if not _is_official_calpeda_pdf_url(low):
        return False
    if "datasheet" in low or "technical" in low or "ficha" in low:
        return False
    return any(marker in low for marker in ("catalogo", "catalogue", "tarifa", "price", "listino"))


def _tariff_catalog_pdf_candidates(catalog_rows: list[dict]) -> list[str]:
    candidates: list[str] = []
    for row in catalog_rows:
        pdf_url = clean_spaces(row.get("pdf_url", ""))
        if not _is_tariff_catalog_pdf_url(pdf_url):
            continue
        if pdf_url not in candidates:
            candidates.append(pdf_url)
    return candidates


def _pick_tariff_catalog_pdf_url(catalog_rows: list[dict]) -> str:
    candidates = _tariff_catalog_pdf_candidates(catalog_rows)
    if not candidates:
        return ""

    return max(candidates, key=lambda pdf_url: (_pdf_url_language_rank(pdf_url), len(pdf_url)))


def _classify_pdf_kind(pdf_url: str) -> tuple[str, str]:
    low = clean_spaces(pdf_url).lower()
    language_rank = _pdf_url_language_rank(low)

    tech_markers = [
        "datasheet",
        "data-sheet",
        "ficha-tecnica",
        "ficha_tecnica",
        "fichatecnica",
        "technical-data",
        "technical_datasheet",
        "technical-datasheet",
        "scheda-tecnica",
        "hoja-de-datos",
    ]
    catalog_markers = [
        "/cataloghi_pdf/",
        "catalogo",
        "catalogue",
        "catalog",
    ]

    if any(marker in low for marker in tech_markers):
        return "resolved_ficha_tecnica", "ficha_tecnica"

    if language_rank > 0 and any(marker in low for marker in catalog_markers):
        return "resolved_catalogo_producto", "catalogo_producto"

    return "resolved_catalogo_producto", "catalogo_producto"


def _build_match_diagnostics(reference: str, name: str, matched_row: dict | None, best_score: int) -> dict:
    if matched_row is None:
        return {
            "match_review_flag": "",
            "match_review_reasons": "",
            "match_ref_exact": "",
            "match_name_token_overlap": "",
        }

    query_hints = _query_hints(reference, name)
    query_text = f"{reference} {name} {query_hints}".strip()

    ref_norm = _normalize(reference)
    ref_compact = _compact(reference)
    matched_ref = clean_spaces(matched_row.get("supplier_ref", ""))
    matched_ref_norm = _normalize(matched_ref)
    matched_ref_compact = _compact(matched_ref)

    query_compact = _compact(query_text)
    matched_name = clean_spaces(matched_row.get("name", ""))
    matched_name_compact = _compact(matched_name)
    matched_name_tokens = _tokens(matched_name)

    query_tokens = set(_tokens(query_text))
    matched_tokens = set(_tokens(f"{matched_ref} {matched_name}"))
    overlap = query_tokens & matched_tokens

    ref_exact = bool(
        ref_norm and matched_ref_norm and (
            ref_norm == matched_ref_norm or (ref_compact and ref_compact == matched_ref_compact)
        )
    )
    matched_name_in_query = bool(
        matched_name_compact and len(matched_name_compact) >= 3 and matched_name_compact in query_compact
    )
    matched_name_is_generic = len(matched_name_tokens) <= 1 and len(matched_name_compact) <= 3

    reasons: list[str] = []
    if best_score < 120:
        reasons.append("low_score")
    if not ref_exact:
        reasons.append("ref_not_exact")
    if len(overlap) == 0:
        reasons.append("name_overlap_0")
    elif len(overlap) == 1:
        reasons.append("name_overlap_1")
    if not matched_name_in_query and not matched_name_is_generic:
        reasons.append("matched_name_not_in_query")

    review_flag = ""
    if best_score < 120 or (not ref_exact and len(overlap) == 0 and best_score < 250):
        review_flag = "review_manual"

    return {
        "match_review_flag": review_flag,
        "match_review_reasons": "|".join(reasons),
        "match_ref_exact": "yes" if ref_exact else "no",
        "match_name_token_overlap": str(len(overlap)),
    }


def _build_image_diagnostics(
    reference: str,
    name: str,
    matched_row: dict | None,
    ranked_rows: list[tuple[int, dict]],
    match_diagnostics: dict,
) -> dict:
    image_url = clean_spaces((matched_row or {}).get("image_url", ""))
    if not matched_row or not image_url:
        return {
            "image_suspect": "",
            "image_review_reason": "",
            "image_match_scope": "",
        }

    reasons: list[str] = []
    query_family_tokens = set(_tokens(f"{reference} {name}"))
    matched_family_tokens = set(_tokens(f"{matched_row.get('supplier_ref', '')} {matched_row.get('name', '')}"))

    ref_exact = match_diagnostics.get("match_ref_exact") == "yes"
    if not ref_exact:
        reasons.append("ref_not_exact")

    try:
        overlap = int(match_diagnostics.get("match_name_token_overlap") or "0")
    except ValueError:
        overlap = 0

    if overlap == 0:
        reasons.append("name_overlap_0")
    elif overlap == 1:
        reasons.append("name_overlap_1")

    matched_ref_compact = _compact(clean_spaces(matched_row.get("supplier_ref", "")))
    matched_name_compact = _compact(clean_spaces(matched_row.get("name", "")))
    if matched_ref_compact and len(matched_ref_compact) <= 3:
        reasons.append("generic_catalog_ref")
    if matched_name_compact and len(matched_name_compact) <= 3:
        reasons.append("generic_catalog_name")

    best_score = ranked_rows[0][0] if ranked_rows else 0
    close_competitor_count = 0
    alternate_image_count = 0
    same_family_alternate_image_count = 0
    for score, row in ranked_rows[1:]:
        if best_score - score > 25:
            break
        close_competitor_count += 1
        candidate_image = clean_spaces(row.get("image_url", ""))
        if candidate_image and candidate_image != image_url:
            alternate_image_count += 1
            candidate_family_tokens = set(_tokens(f"{row.get('supplier_ref', '')} {row.get('name', '')}"))
            if (
                candidate_family_tokens
                and matched_family_tokens
                and query_family_tokens
                and candidate_family_tokens & matched_family_tokens
                and candidate_family_tokens & query_family_tokens
            ):
                same_family_alternate_image_count += 1

    if close_competitor_count:
        reasons.append("close_candidate_scores")
    if alternate_image_count:
        reasons.append("close_candidates_with_other_images")
    same_family_close_candidates = same_family_alternate_image_count > 0
    if same_family_close_candidates:
        reasons.append("same_family_close_candidates")

    has_generic_match = (
        "generic_catalog_ref" in reasons
        or "generic_catalog_name" in reasons
    )
    family_variant_conflict = (
        not ref_exact
        and has_generic_match
        and _has_extended_family_variant(query_family_tokens, matched_family_tokens)
    )
    if family_variant_conflict:
        reasons.append("family_variant_extension")

    weak_image_evidence = (not ref_exact and overlap == 0) or has_generic_match
    ambiguous_competition = alternate_image_count > same_family_alternate_image_count
    if not ambiguous_competition and close_competitor_count > 0 and not ref_exact:
        ambiguous_competition = same_family_alternate_image_count == 0

    suspect = ""
    if ambiguous_competition or family_variant_conflict:
        suspect = "yes"

    match_scope = "sku"
    if ambiguous_competition or family_variant_conflict:
        match_scope = "ambiguous"
    elif weak_image_evidence:
        match_scope = "family"
    elif same_family_close_candidates and not ref_exact:
        match_scope = "family"

    return {
        "image_suspect": suspect,
        "image_review_reason": "|".join(reasons),
        "image_match_scope": match_scope,
    }


def _manual_strict_review_applies(reference: str) -> bool:
    return _compact(reference) in MANUAL_STRICT_REVIEW_REFERENCES


def _is_manual_accessory_reference(reference: str) -> bool:
    return _compact(reference) == _compact(MANUAL_ACCESSORY_REFERENCE)


def _is_manual_pmat_reference(reference: str) -> bool:
    return _compact(reference) in {_compact(item) for item in MANUAL_PMAT_REFERENCES}


def _is_official_manual_accessory_catalog_row(row: dict) -> bool:
    pdf_url = clean_spaces(row.get("pdf_url", ""))
    source_url = clean_spaces(row.get("source_url", ""))
    row_blob = _normalize(
        " ".join(
            [
                row.get("supplier_ref", ""),
                row.get("name", ""),
                row.get("search_text", ""),
                pdf_url,
                source_url,
            ]
        )
    )
    url_blob = f"{pdf_url} {source_url}".lower()

    if "calpeda.com" not in url_blob:
        return False
    if not pdf_url:
        return False
    if "AKO" not in row_blob:
        return False
    if not re.search(r"\b531\d{2}\b", row_blob):
        return False
    if "INTERRUPTOR" not in row_blob:
        return False
    if "NIVEL" not in row_blob and "NIVELL" not in row_blob:
        return False

    return True


def _resolve_manual_accessory_reference(
    reference: str,
    name: str,
    ranked_rows: list[tuple[int, dict]],
    catalog_rows: list[dict],
) -> dict:
    matched_row = ranked_rows[0][1] if ranked_rows else None
    matched_score = ranked_rows[0][0] if ranked_rows else -1

    safe_rows = [row for row in catalog_rows if _is_official_manual_accessory_catalog_row(row)]
    safe_ranked_rows = _rank_catalog_rows(reference, name, safe_rows) if safe_rows else []
    safe_row = safe_ranked_rows[0][1] if safe_ranked_rows else None
    safe_pdf_url = clean_spaces((safe_row or {}).get("pdf_url", ""))
    safe_matched_name = clean_spaces((safe_row or {}).get("name", ""))
    safe_matched_ref = clean_spaces((safe_row or {}).get("supplier_ref", ""))
    safe_source_url = clean_spaces((safe_row or {}).get("source_url", ""))

    matched_name = clean_spaces((matched_row or {}).get("name", ""))
    matched_ref = clean_spaces((matched_row or {}).get("supplier_ref", ""))
    source_url = clean_spaces((matched_row or {}).get("source_url", ""))

    notes = [
        "calpeda_manual_review:accessory_valid",
        "calpeda_rejected_wrong_pdf_non_matching",
        "calpeda_manual_review:image_empty",
        "calpeda_rejected_empty_image",
    ]

    if safe_row:
        notes.extend([
            "calpeda_accessory_catalog_match",
            "calpeda_tarifa_global_candidate",
            "calpeda_tarifa_global_preferred",
        ])
        matched_name = safe_matched_name
        matched_ref = safe_matched_ref
        source_url = safe_source_url
        matched_score = safe_ranked_rows[0][0]
        resolver_status = "resolved_catalogo_producto"
        preferred_pdf_kind = "catalogo_producto"
        preferred_doc_type = "catalogo_producto"
        preferred_title = safe_matched_name
        preferred_pdf_url = CALPEDA_TARIFA_GLOBAL_URL
        preferred_pdf_label = safe_matched_name
    else:
        notes.append("calpeda_needs_official_accessory_catalog_match")
        resolver_status = "not_found"
        preferred_pdf_kind = ""
        preferred_doc_type = ""
        preferred_title = ""
        preferred_pdf_url = ""
        preferred_pdf_label = ""

    return {
        "resolver_status": resolver_status,
        "reference": reference,
        "name": name,
        "matched_catalog_name": matched_name,
        "matched_catalog_ref": matched_ref,
        "matched_catalog_score": str(matched_score) if matched_score >= 0 else "",
        "product_page_url": source_url,
        "product_page_title": matched_name,
        "resolved_image_url": "",
        "preferred_pdf_kind": preferred_pdf_kind,
        "preferred_pdf_label": preferred_pdf_label,
        "preferred_pdf_url": preferred_pdf_url,
        "preferred_pdf_check_ok": "",
        "preferred_pdf_content_type": "",
        "preferred_doc_type": preferred_doc_type,
        "preferred_title": preferred_title,
        "fallback_doc_type": "",
        "fallback_title": "",
        "fallback_pdf_url": "",
        "image_suspect": "yes",
        "image_review_reason": "manual_review|image_empty",
        "image_match_scope": "ambiguous",
        "match_review_flag": "review_manual",
        "match_review_reasons": "manual_accessory_review",
        "match_ref_exact": "yes" if safe_row else "no",
        "match_name_token_overlap": "",
        "notes": " | ".join(notes),
    }


def _matched_family_signature_is_safe(reference: str, name: str, matched_row: dict | None, diagnostics: dict) -> bool:
    if not matched_row:
        return False

    if diagnostics.get("match_ref_exact") == "yes":
        return True

    query_text = f"{reference} {name}".strip()
    query_compact = _compact(query_text)
    query_tokens = set(_tokens(query_text))

    matched_ref = clean_spaces(matched_row.get("supplier_ref", ""))
    matched_name = clean_spaces(matched_row.get("name", ""))
    matched_text = f"{matched_ref} {matched_name}".strip()
    matched_tokens = {
        token for token in _tokens(matched_text)
        if any(ch.isalpha() for ch in token)
    }

    if len(matched_tokens) == 1:
        token = next(iter(matched_tokens))
        if token in query_tokens:
            return True

    matched_signatures = {
        _compact(matched_ref),
        _compact(matched_name),
    }
    for signature in matched_signatures:
        if len(signature) >= 4 and signature in query_compact:
            return True

    return False


def _is_generic_image_match(matched_row: dict | None) -> bool:
    if not matched_row:
        return False

    matched_ref_compact = _compact(clean_spaces(matched_row.get("supplier_ref", "")))
    matched_name_compact = _compact(clean_spaces(matched_row.get("name", "")))
    return (
        (matched_ref_compact and len(matched_ref_compact) <= 3)
        or (matched_name_compact and len(matched_name_compact) <= 3)
    )


def _build_not_found(reference: str, name: str) -> dict:
    return {
        "resolver_status": "not_found",
        "reference": clean_spaces(reference),
        "name": clean_spaces(name),
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
        "image_suspect": "",
        "image_review_reason": "",
        "image_match_scope": "",
        "match_review_flag": "",
        "match_review_reasons": "",
        "match_ref_exact": "",
        "match_name_token_overlap": "",
        "notes": "calpeda_no_search_text_match",
    }


def _build_skipped_non_calpeda(reference: str, name: str) -> dict:
    result = _build_not_found(reference, name)
    result["resolver_status"] = "skipped_non_calpeda_row"
    result["notes"] = "calpeda_skipped_non_calpeda_row:name_without_calpeda"
    return result


def _looks_like_calpeda_row(reference: str, name: str, catalog_rows: list[dict]) -> bool:
    name_norm = _normalize(name)
    if "CALPEDA" in name_norm:
        return True

    if name_norm:
        return False

    ref_norm = _normalize(reference)
    ref_compact = _compact(reference)
    for row in catalog_rows:
        row_ref = clean_spaces(row.get("supplier_ref", ""))
        if not row_ref:
            continue
        if ref_norm and ref_norm == _normalize(row_ref):
            return True
        if ref_compact and ref_compact == _compact(row_ref):
            return True

    return False


def resolve_reference(reference: str, name: str, catalog_rows: list[dict]) -> dict:
    reference = clean_spaces(reference)
    name = clean_spaces(name)

    if not catalog_rows:
        result = _build_not_found(reference, name)
        result["notes"] = "calpeda_catalog_empty"
        return result

    if not _looks_like_calpeda_row(reference, name, catalog_rows):
        return _build_skipped_non_calpeda(reference, name)

    ranked_rows = _rank_catalog_rows(reference, name, catalog_rows)
    best_row = ranked_rows[0][1] if ranked_rows else None
    best_score = ranked_rows[0][0] if ranked_rows else -1

    if best_row is None or best_score < 35:
        return _build_not_found(reference, name)

    if _is_manual_accessory_reference(reference):
        return _resolve_manual_accessory_reference(reference, name, ranked_rows, catalog_rows)

    image_url = clean_spaces(best_row.get("image_url", ""))
    pdf_url = clean_spaces(best_row.get("pdf_url", ""))
    matched_name = clean_spaces(best_row.get("name", ""))
    matched_ref = clean_spaces(best_row.get("supplier_ref", ""))
    source_url = clean_spaces(best_row.get("source_url", ""))
    diagnostics = _build_match_diagnostics(reference, name, best_row, best_score)
    image_diagnostics = _build_image_diagnostics(reference, name, best_row, ranked_rows, diagnostics)
    notes = ["calpeda_search_text_match"]

    manual_strict_review = _manual_strict_review_applies(reference)
    family_match_safe = _matched_family_signature_is_safe(reference, name, best_row, diagnostics)
    reject_pdf_for_manual_review = manual_strict_review and not family_match_safe
    reject_image_manual_no_corresponde = reject_pdf_for_manual_review and _compact(reference) == _compact(MANUAL_IMAGE_NO_CORRESPONDE_REFERENCE)
    reject_generic_image_for_manual_review = (
        reject_pdf_for_manual_review
        and not reject_image_manual_no_corresponde
        and _is_generic_image_match(best_row)
    )
    manual_pmat_match = (
        _is_manual_pmat_reference(reference)
        and clean_spaces(pdf_url) == MANUAL_PMAT_PDF_URL
        and _compact(matched_ref) == _compact(reference)
    )

    if reject_pdf_for_manual_review:
        pdf_url = ""
        resolver_status = "not_found"
        preferred_pdf_kind = ""
        preferred_doc_type = ""
        preferred_title = ""
        notes.extend([
            "calpeda_manual_review:ft_no_corresponde",
            "calpeda_rejected_pdf_family_mismatch",
        ])
    elif CALPEDA_TARIFA_GLOBAL_URL:
        pdf_url = CALPEDA_TARIFA_GLOBAL_URL
        resolver_status = "resolved_catalogo_producto"
        preferred_pdf_kind = "catalogo_producto"
        preferred_doc_type = "catalogo_producto"
        preferred_title = matched_name
        notes.extend([
            "calpeda_tarifa_global_candidate",
            "calpeda_tarifa_global_preferred",
        ])
    elif manual_pmat_match:
        resolver_status = "resolved_ficha_tecnica"
        preferred_pdf_kind = "ficha_tecnica"
        preferred_doc_type = "ficha_tecnica"
        preferred_title = matched_name
        notes.extend([
            "calpeda_manual_verified:pmat_accessory",
            "calpeda_pdf_language_fallback:en_official_only",
        ])
    elif pdf_url:
        resolver_status, preferred_pdf_kind = _classify_pdf_kind(pdf_url)
        preferred_doc_type = preferred_pdf_kind
        preferred_title = matched_name
    elif image_url:
        resolver_status = "resolved_image_only"
        preferred_pdf_kind = ""
        preferred_doc_type = ""
        preferred_title = ""
    else:
        resolver_status = "not_found"
        preferred_pdf_kind = ""
        preferred_doc_type = ""
        preferred_title = ""

    if manual_pmat_match and image_url:
        image_diagnostics["image_suspect"] = ""
        image_diagnostics["image_review_reason"] = ""
        image_diagnostics["image_match_scope"] = "family"
        notes.append("calpeda_image_scope:official_accessory_family")

    if reject_image_manual_no_corresponde and image_url:
        image_url = ""
        image_diagnostics["image_suspect"] = "yes"
        image_diagnostics["image_match_scope"] = "ambiguous"
        existing_reason = clean_spaces(image_diagnostics.get("image_review_reason", ""))
        extra_reasons = [
            reason for reason in [
                existing_reason,
                "manual_review",
                "family_mismatch",
            ] if reason
        ]
        image_diagnostics["image_review_reason"] = "|".join(extra_reasons)
        notes.append("calpeda_rejected_image_family_mismatch")
        notes.append("calpeda_manual_review:image_no_corresponde")
    elif reject_generic_image_for_manual_review and image_url:
        image_url = ""
        image_diagnostics["image_suspect"] = "yes"
        image_diagnostics["image_match_scope"] = "ambiguous"
        existing_reason = clean_spaces(image_diagnostics.get("image_review_reason", ""))
        extra_reasons = [
            reason for reason in [
                existing_reason,
                "generic_catalog_image",
                "family_mismatch",
            ] if reason
        ]
        image_diagnostics["image_review_reason"] = "|".join(extra_reasons)
        notes.append("calpeda_rejected_generic_image_family_mismatch")

    return {
        "resolver_status": resolver_status,
        "reference": reference,
        "name": name,
        "matched_catalog_name": matched_name,
        "matched_catalog_ref": matched_ref,
        "matched_catalog_score": str(best_score),
        "product_page_url": source_url,
        "product_page_title": matched_name,
        "resolved_image_url": image_url,
        "preferred_pdf_kind": preferred_pdf_kind,
        "preferred_pdf_label": matched_name if pdf_url else "",
        "preferred_pdf_url": pdf_url,
        "preferred_pdf_check_ok": "",
        "preferred_pdf_content_type": "",
        "preferred_doc_type": preferred_doc_type,
        "preferred_title": preferred_title,
        "fallback_doc_type": "",
        "fallback_title": "",
        "fallback_pdf_url": "",
        "image_suspect": image_diagnostics["image_suspect"],
        "image_review_reason": image_diagnostics["image_review_reason"],
        "image_match_scope": image_diagnostics["image_match_scope"],
        "match_review_flag": diagnostics["match_review_flag"],
        "match_review_reasons": diagnostics["match_review_reasons"],
        "match_ref_exact": diagnostics["match_ref_exact"],
        "match_name_token_overlap": diagnostics["match_name_token_overlap"],
        "notes": " | ".join(
            [
                x for x in notes + [
                    f"match_review:{diagnostics['match_review_reasons']}" if diagnostics["match_review_flag"] else "",
                    f"image_review:{image_diagnostics['image_review_reason']}" if image_diagnostics["image_suspect"] else "",
                ] if x
            ]
        ),
    }

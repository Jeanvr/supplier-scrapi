from __future__ import annotations

import argparse
import re
from pathlib import Path

from src.core.pdf_tools.pdf_operations import (
    TrimDecision,
    extract_pdf_text,
    find_reference_pages,
    group_consecutive_pages,
    pick_reference_block,
    build_final_pages,
    merge_selected_pages,
    normalize_reference,
)

# Reglas específicas de Calpeda
CODE_RE = re.compile(r"\bE[A-Z0-9]{8,}\b")
TITLE_JUNK_RE = re.compile(
    r"(cat[aá]logo\s*-\s*tarifa|marzo\s+2025|edici[oó]n|^\d+$|^products$)",
    re.IGNORECASE,
)


def _clean_top_lines(page_text: str, limit: int = 12) -> list[str]:
    lines: list[str] = []
    for raw_line in page_text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if TITLE_JUNK_RE.search(line):
            continue
        lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def _is_title_like(line: str) -> bool:
    if len(line) < 2 or len(line) > 90:
        return False
    if "€" in line:
        return False
    if CODE_RE.search(line):
        return False
    letters = sum(ch.isalpha() for ch in line)
    upper = sum(ch.isupper() for ch in line if ch.isalpha())
    if letters < 2:
        return False
    return upper >= max(2, int(letters * 0.5))


def _score_visual_candidate(page_number: int, page_text: str, ref_page: int) -> int:
    top_lines = _clean_top_lines(page_text)
    if not top_lines:
        return -999

    code_count = len(set(CODE_RE.findall(page_text)))
    has_precio = "PRECIO" in page_text.upper()
    has_codigo = "CÓDIGO" in page_text.upper() or "CODIGO" in page_text.upper()
    title_score = 0

    if _is_title_like(top_lines[0]):
        title_score += 5
    if len(top_lines) > 1 and not CODE_RE.search(top_lines[1]) and len(top_lines[1]) <= 120:
        title_score += 3

    score = title_score
    score += max(0, 4 - abs(ref_page - page_number))
    if code_count == 0:
        score += 4
    elif code_count <= 2:
        score += 2
    else:
        score -= min(code_count, 8)

    if has_precio:
        score -= 3
    if has_codigo:
        score -= 2

    return score


def _find_visual_page_near_block(block: list[int], pages: list[str]) -> int | None:
    if not block:
        return None

    ref_page = block[0]
    candidates: list[tuple[int, int]] = []
    for page_number in range(max(1, ref_page - 3), ref_page):
        score = _score_visual_candidate(page_number, pages[page_number - 1], ref_page)
        candidates.append((score, page_number))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best_score, best_page = candidates[0]
    if best_score < 6:
        return None
    return best_page





def trim_pdf_for_reference(pdf_path: Path, reference: str, output_pdf: Path) -> TrimDecision:
    """Recorta un PDF Calpeda a 1-3 páginas útiles para una referencia exacta.
    
    Usa el motor genérico y aplica heurísticas específicas de Calpeda para
    elegir la página visual (portada/índice).
    
    Args:
        pdf_path: Ruta del PDF fuente.
        reference: Referencia exacta a localizar.
        output_pdf: Ruta del PDF recortado de salida.
        
    Returns:
        TrimDecision con detalles del análisis y rutas finales.
    """
    pages = extract_pdf_text(pdf_path)
    reference_pages = find_reference_pages(reference, pages)
    if not reference_pages:
        raise ValueError(f"No se encontró la referencia exacta en el PDF: {reference}")

    reference_blocks = group_consecutive_pages(reference_pages)
    chosen_reference_block = pick_reference_block(reference_blocks)
    visual_page = _find_visual_page_near_block(chosen_reference_block, pages)
    final_pages = build_final_pages(chosen_reference_block, visual_page)

    merge_selected_pages(pdf_path, final_pages, output_pdf)

    return TrimDecision(
        reference=normalize_reference(reference),
        reference_pages=reference_pages,
        reference_blocks=reference_blocks,
        chosen_reference_block=chosen_reference_block,
        visual_page=visual_page,
        final_pages=final_pages,
        output_pdf=output_pdf,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recorta un PDF catálogo Calpeda a 1-3 páginas útiles para una referencia exacta.")
    parser.add_argument("--pdf", required=True, help="Ruta del PDF fuente")
    parser.add_argument("--reference", required=True, help="Referencia exacta a localizar")
    parser.add_argument("--out", required=True, help="Ruta del PDF recortado de salida")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    decision = trim_pdf_for_reference(
        pdf_path=Path(args.pdf),
        reference=args.reference,
        output_pdf=Path(args.out),
    )

    print(f"reference: {decision.reference}")
    print(f"reference_pages: {decision.reference_pages}")
    print(f"reference_blocks: {decision.reference_blocks}")
    print(f"chosen_reference_block: {decision.chosen_reference_block}")
    print(f"visual_page: {decision.visual_page or '-'}")
    print(f"final_pages: {decision.final_pages}")
    print(f"output_pdf: {decision.output_pdf}")


if __name__ == "__main__":
    main()

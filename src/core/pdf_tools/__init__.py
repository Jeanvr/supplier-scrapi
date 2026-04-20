"""Herramientas genéricas para procesamiento y recorte de PDFs."""

from .pdf_operations import (
    TrimDecision,
    extract_pdf_text,
    find_reference_pages,
    group_consecutive_pages,
    pick_reference_block,
    build_final_pages,
    merge_selected_pages,
)

__all__ = [
    "TrimDecision",
    "extract_pdf_text",
    "find_reference_pages",
    "group_consecutive_pages",
    "pick_reference_block",
    "build_final_pages",
    "merge_selected_pages",
]

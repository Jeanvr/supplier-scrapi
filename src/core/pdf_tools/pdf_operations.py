"""Motor genérico para recorte de PDFs por referencia exacta.

Funciones reutilizables para:
- Extraer texto de PDFs
- Buscar referencias exactas
- Agrupar páginas consecutivas
- Seleccionar bloques compactos
- Construir lista final de páginas
- Generar PDF recortado
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TrimDecision:
    """Resultado del análisis y recorte de un PDF por referencia."""
    reference: str
    reference_pages: list[int]
    reference_blocks: list[list[int]]
    chosen_reference_block: list[int]
    visual_page: int | None
    final_pages: list[int]
    output_pdf: Path


def _require_binary(name: str) -> str:
    """Verifica que una utilidad binaria esté disponible."""
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"No se encontró la utilidad requerida: {name}")
    return path


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Ejecuta un comando en la shell."""
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def extract_pdf_text(pdf_path: Path) -> list[str]:
    """Extrae texto de un PDF, una página por elemento.
    
    Args:
        pdf_path: Ruta del PDF.
        
    Returns:
        Lista de strings, uno por página (sin separador de página).
    """
    _require_binary("pdftotext")

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        _run(["pdftotext", "-enc", "UTF-8", "-layout", str(pdf_path), str(tmp_path)])
        text = tmp_path.read_text(encoding="utf-8", errors="ignore")
    finally:
        tmp_path.unlink(missing_ok=True)

    pages = [page.replace("\x00", "").strip() for page in text.split("\f")]
    while pages and not pages[-1]:
        pages.pop()
    return pages


def normalize_reference(reference: str) -> str:
    """Normaliza una referencia: trim + uppercase."""
    return reference.strip().upper()


def reference_regex(reference: str) -> re.Pattern[str]:
    """Retorna un patrón regex para buscar una referencia exacta.
    
    La referencia debe estar rodeada de límites de palabra (no alfanuméricos).
    """
    escaped = re.escape(normalize_reference(reference))
    return re.compile(rf"(?<![A-Z0-9]){escaped}(?![A-Z0-9])", re.IGNORECASE)


def find_reference_pages(reference: str, pages: list[str]) -> list[int]:
    """Busca páginas que contienen la referencia exacta.
    
    Args:
        reference: Referencia a buscar.
        pages: Lista de strings (texto de cada página).
        
    Returns:
        Lista de números de página (1-indexed) que contienen la referencia.
    """
    ref_re = reference_regex(reference)
    out: list[int] = []
    for idx, page_text in enumerate(pages, start=1):
        if ref_re.search(page_text.upper()):
            out.append(idx)
    return out


def group_consecutive_pages(pages: list[int]) -> list[list[int]]:
    """Agrupa números de página consecutivos.
    
    Args:
        pages: Lista de números de página.
        
    Returns:
        Lista de bloques, cada bloque es una lista de páginas consecutivas.
    """
    if not pages:
        return []

    groups: list[list[int]] = [[pages[0]]]
    for page in pages[1:]:
        if page == groups[-1][-1] + 1:
            groups[-1].append(page)
        else:
            groups.append([page])
    return groups


def pick_reference_block(blocks: list[list[int]]) -> list[int]:
    """Elige el bloque más compacto de entre varios bloques.
    
    Criterios (en orden):
    1. Menor cantidad de páginas.
    2. Menor span (diferencia entre primera y última).
    3. Primer bloque (si hay empate).
    
    Args:
        blocks: Lista de bloques de páginas.
        
    Returns:
        El bloque más compacto, o lista vacía si no hay bloques.
    """
    if not blocks:
        return []

    def key(block: list[int]) -> tuple[int, int, int]:
        span = block[-1] - block[0]
        return (-len(block), span, block[0])

    return min(blocks, key=key)


def build_final_pages(reference_block: list[int], visual_page: int | None) -> list[int]:
    """Construye la lista final de páginas a incluir.
    
    Si hay página visual, va primero. Luego el bloque de referencia.
    Máximo 3 páginas.
    
    Args:
        reference_block: Bloque de páginas donde aparece la referencia.
        visual_page: Página visual opcional (portada/índice).
        
    Returns:
        Lista ordenada de páginas finales (máx 3).
    """
    final_pages: list[int] = []
    if visual_page is not None:
        final_pages.append(visual_page)

    for page in reference_block:
        if page not in final_pages:
            final_pages.append(page)

    return final_pages[:3]


def merge_selected_pages(pdf_path: Path, selected_pages: list[int], output_pdf: Path) -> None:
    """Genera un nuevo PDF con solo las páginas seleccionadas.
    
    Args:
        pdf_path: Ruta del PDF fuente.
        selected_pages: Lista de números de página a incluir (1-indexed).
        output_pdf: Ruta del PDF de salida.
    """
    _require_binary("gs")

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    page_list = ",".join(str(page) for page in selected_pages)
    _run(
        [
            "gs",
            "-sDEVICE=pdfwrite",
            "-dNOPAUSE",
            "-dBATCH",
            "-dSAFER",
            f"-sPageList={page_list}",
            f"-sOutputFile={output_pdf}",
            str(pdf_path),
        ]
    )

"""Orquestador multi-proveedor para resolución de documentos y imágenes.

Permite procesar un único Excel con filas de múltiples proveedores,
delegando cada fila al resolver específico del proveedor.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pandas as pd

from src.core.text import clean_spaces
from src.providers.loader import load_provider


def normalize_provider_key(raw_brand: str) -> str:
    """Normaliza nombre de proveedor a clave estándar."""
    normalized = clean_spaces(raw_brand).casefold()
    if not normalized:
        return ""

    if "bosch" in normalized or "junkers" in normalized:
        return "bosch"
    if "calpeda" in normalized:
        return "calpeda"
    if "grundfos" in normalized:
        return "grundfos"
    if "ariston" in normalized:
        return "ariston"

    return re.sub(r"[^a-z0-9]+", "", normalized)


def detect_provider_from_row(row: pd.Series, provider_col: str | None = None) -> str | None:
    """Detecta el proveedor de una fila.
    
    Intenta en orden:
    1. Columna provider_col si está especificada
    2. Columnas alternativas: 'marca', 'proveedor', 'provider'
    3. Retorna None si no es detectable
    """
    if provider_col and provider_col in row.index:
        val = clean_spaces(row.get(provider_col, ""))
        if val:
            return normalize_provider_key(val)
    
    # Buscar columnas alternativas
    for col_name in ["marca", "proveedor", "provider", "Marca", "Proveedor", "Provider"]:
        if col_name in row.index:
            val = clean_spaces(row.get(col_name, ""))
            if val:
                return normalize_provider_key(val)
    
    return None


def pick_column(df: pd.DataFrame, aliases: list[str], required: bool = True) -> str:
    """Encuentra una columna en el DataFrame por alias."""
    normalized = {clean_spaces(col).casefold(): col for col in df.columns}
    for alias in aliases:
        match = normalized.get(clean_spaces(alias).casefold())
        if match:
            return match

    if required:
        raise ValueError(f"No se encontró ninguna columna válida entre: {aliases}")

    return ""


def run_multi_provider_resolver(
    *,
    excel: str,
    out: str,
    provider_col: str | None = None,
    download: bool = False,
    images_base_dir: str = "data/output/images",
    pdfs_base_dir: str = "data/output/pdfs",
) -> None:
    """Resuelve un Excel con múltiples proveedores.
    
    Args:
        excel: Ruta del Excel de entrada con filas de múltiples proveedores
        out: Ruta del Excel de salida
        provider_col: Nombre de columna que indica el proveedor (opcional)
        download: Si True, descarga imágenes y PDFs resueltos
        images_base_dir: Directorio base para imágenes
        pdfs_base_dir: Directorio base para PDFs
    """
    from src.core.excel_runner import run_excel_resolver
    
    excel_path = Path(excel)
    out_path = Path(out)

    if not excel_path.exists():
        raise FileNotFoundError(f"No existe el Excel: {excel_path}")

    df = pd.read_excel(excel_path, dtype=str).fillna("")
    print(f"Total filas: {len(df)}")

    # Agrupar filas por proveedor
    provider_groups: dict[str, list[int]] = {}
    provider_errors: list[dict] = []

    for idx, row in df.iterrows():
        provider = detect_provider_from_row(row, provider_col)
        if not provider:
            provider_errors.append({
                "row_index": idx,
                "error": "No se detectó proveedor",
                "provider_detected": None,
            })
            continue

        if provider not in provider_groups:
            provider_groups[provider] = []
        provider_groups[provider].append(idx)

    print(f"Proveedores detectados: {list(provider_groups.keys())}")
    if provider_errors:
        print(f"Filas sin proveedor detectable: {len(provider_errors)}")

    all_results = {}
    provider_statuses = {}

    with tempfile.TemporaryDirectory(prefix="multi_provider_resolver_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)

        for provider_key, row_indices in provider_groups.items():
            print(f"\n[{provider_key.upper()}] Procesando {len(row_indices)} filas...")
            
            try:
                provider = load_provider(provider_key)
            except Exception as e:
                print(f"  ERROR: No se puede cargar proveedor {provider_key}: {e}")
                provider_statuses[provider_key] = "not_implemented"
                continue

            subset_df = df.iloc[row_indices].copy()
            temp_excel = temp_dir / f"{provider_key}_input.xlsx"
            temp_output = temp_dir / f"{provider_key}_output.xlsx"
            subset_df.to_excel(temp_excel, index=False)

            try:
                images_dir = str(Path(images_base_dir) / f"{provider_key}_resolved")
                pdfs_dir = str(Path(pdfs_base_dir) / f"{provider_key}_resolved")

                run_excel_resolver(
                    excel=str(temp_excel),
                    out=str(temp_output),
                    catalog_jsonl=provider.get("default_catalog_jsonl", ""),
                    ref_aliases=provider["ref_aliases"],
                    name_aliases=provider["name_aliases"],
                    load_catalog_rows=provider["load_catalog_rows"],
                    resolve_reference=provider["resolve_reference"],
                    postprocess_results=provider.get("postprocess_results"),
                    attach_downloads_fn=provider.get("attach_downloads_fn"),
                    download=download,
                    images_dir=images_dir,
                    pdfs_dir=pdfs_dir,
                    catalog_label=provider.get("catalog_label", f"{provider_key}_catalog_rows"),
                )

                results_df = pd.read_excel(temp_output, dtype=str).fillna("")
                
                for out_idx, original_idx in enumerate(row_indices):
                    if out_idx < len(results_df):
                        result_row = results_df.iloc[out_idx].to_dict()
                        result_row["provider_detected"] = provider_key
                        result_row["provider_resolver"] = "completed"
                        all_results[original_idx] = result_row

                provider_statuses[provider_key] = "completed"
                print(f"  ok: {provider_key}: {len(row_indices)} filas procesadas")

            except Exception as e:
                print(f"  ERROR: {e}")
                provider_statuses[provider_key] = "error"
                for original_idx in row_indices:
                    all_results[original_idx] = {
                        "provider_detected": provider_key,
                        "provider_resolver": "error",
                        "notes": str(e),
                    }

    # Marcar filas sin proveedor detectado
    for error_info in provider_errors:
        idx = error_info["row_index"]
        all_results[idx] = {
            "provider_detected": None,
            "provider_resolver": "not_detected",
            "notes": error_info["error"],
        }

    # Recombinar: filas originales + resultados resueltos
    output_rows = []
    for idx in range(len(df)):
        original_row = df.iloc[idx].to_dict()
        resolved = all_results.get(idx, {})
        
        # Mergear original + resuelto
        combined = {**original_row, **resolved}
        output_rows.append(combined)

    output_df = pd.DataFrame(output_rows)

    # Guardar
    out_path.parent.mkdir(parents=True, exist_ok=True)
    output_df.to_excel(out_path, index=False)

    # Resumen
    print("\n" + "=" * 70)
    print("RESUMEN MULTI-PROVEEDOR")
    print("=" * 70)
    print(f"Total filas: {len(df)}")
    print(f"Proveedores procesados: {list(provider_statuses.keys())}")
    for prov, status in provider_statuses.items():
        count = len(provider_groups.get(prov, []))
        print(f"  {prov}: {count} filas [{status}]")
    print(f"Filas sin proveedor: {len(provider_errors)}")
    if "resolver_status" in output_df.columns:
        print(f"resolved_ficha_tecnica: {(output_df['resolver_status'] == 'resolved_ficha_tecnica').sum()}")
        print(f"resolved_catalogo_producto: {(output_df['resolver_status'] == 'resolved_catalogo_producto').sum()}")
        print(f"resolved_image_only: {(output_df['resolver_status'] == 'resolved_image_only').sum()}")
        print(f"not_found: {(output_df['resolver_status'] == 'not_found').sum()}")
    if "download_status" in output_df.columns:
        print("download_status:")
        for status, count in output_df["download_status"].fillna("").value_counts().sort_index().items():
            label = status or "(empty)"
            print(f"  {label}: {count}")
    print(f"Output: {out_path}")

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Callable

import pandas as pd

from src.core.text import clean_spaces


DEFAULT_EMPTY_RESULT = {
    "resolver_status": "skipped_empty_reference",
    "reference": "",
    "name": "",
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
    "notes": "fila sin referencia",
}


def pick_column(df: pd.DataFrame, aliases: list[str], required: bool = True) -> str:
    normalized = {clean_spaces(col).casefold(): col for col in df.columns}
    for alias in aliases:
        match = normalized.get(clean_spaces(alias).casefold())
        if match:
            return match

    if required:
        raise ValueError(f"No se encontró ninguna columna válida entre: {aliases}")

    return ""


def build_empty_result(name: str) -> dict:
    result = dict(DEFAULT_EMPTY_RESULT)
    result["name"] = clean_spaces(name)
    return result


def print_summary(output_df: pd.DataFrame, out_path: Path, *, download: bool, pdfs_dir_path: Path) -> None:
    print("\nResumen")
    print(f"  total_rows: {len(output_df)}")

    if "resolver_status" in output_df.columns:
        print(f"  resolved_ficha_tecnica: {(output_df['resolver_status'] == 'resolved_ficha_tecnica').sum()}")
        print(f"  resolved_catalogo_producto: {(output_df['resolver_status'] == 'resolved_catalogo_producto').sum()}")
        print(f"  resolved_image_only: {(output_df['resolver_status'] == 'resolved_image_only').sum()}")
        print(f"  not_found: {(output_df['resolver_status'] == 'not_found').sum()}")

    if "download_status" in output_df.columns:
        print(f"  downloaded_image_and_pdf: {(output_df['download_status'] == 'downloaded_image_and_pdf').sum()}")
        print(f"  downloaded_image_only: {(output_df['download_status'] == 'downloaded_image_only').sum()}")

    print(f"  output: {out_path}")
    if download:
        print(f"  pdfs_dir: {pdfs_dir_path}")


ResolverFn = Callable[..., dict]
PostprocessFn = Callable[[list[dict]], list[dict]]
AttachDownloadsFn = Callable[..., dict]
LoadCatalogRowsFn = Callable[[Path], list[dict]]


def pick_download_reference(result: dict) -> str:
    for key in ("download_reference", "media_reference", "output_reference", "reference"):
        value = clean_spaces(result.get(key, ""))
        if value:
            return value

    return ""


def run_excel_resolver(
    *,
    excel: str,
    out: str,
    catalog_jsonl: str,
    ref_aliases: list[str],
    name_aliases: list[str],
    load_catalog_rows: LoadCatalogRowsFn,
    resolve_reference: ResolverFn,
    postprocess_results: PostprocessFn | None = None,
    attach_downloads_fn: AttachDownloadsFn | None = None,
    download: bool = False,
    images_dir: str,
    pdfs_dir: str,
    catalog_label: str = "catalog_rows",
) -> None:
    excel_path = Path(excel)
    out_path = Path(out)
    catalog_path = Path(catalog_jsonl)
    images_dir_path = Path(images_dir)
    pdfs_dir_path = Path(pdfs_dir)

    if not excel_path.exists():
        raise FileNotFoundError(f"No existe el Excel: {excel_path}")

    df = pd.read_excel(excel_path, dtype=str).fillna("")
    ref_col = pick_column(df, ref_aliases, required=True)
    name_col = pick_column(df, name_aliases, required=False)

    catalog_rows = load_catalog_rows(catalog_path)
    print(f"{catalog_label}: {len(catalog_rows)} | catalog_path: {catalog_path}")

    results = []
    total = len(df)
    resolve_accepts_row = len(inspect.signature(resolve_reference).parameters) >= 4

    for idx, row in df.iterrows():
        reference = clean_spaces(row.get(ref_col, ""))
        name = clean_spaces(row.get(name_col, "")) if name_col else ""

        if not reference:
            result = build_empty_result(name)
        else:
            print(f"[{idx + 1}/{total}] Resolviendo {reference} | {name}")
            if resolve_accepts_row:
                row_context = {str(col): clean_spaces(row.get(col, "")) for col in df.columns}
                result = resolve_reference(reference, name, catalog_rows, row_context)
            else:
                result = resolve_reference(reference, name, catalog_rows)
            print(
                f"  -> provisional {result['resolver_status']} | "
                f"img={'si' if result.get('resolved_image_url') else 'no'} | "
                f"pdf={result.get('preferred_pdf_kind') or '-'}"
            )

        results.append(result)

    if postprocess_results is not None:
        results = postprocess_results(results)

    final_results = []
    for result in results:
        if attach_downloads_fn is not None:
            result = attach_downloads_fn(
                result=result,
                reference=pick_download_reference(result),
                name=clean_spaces(result.get("name", "")),
                download_enabled=download,
                images_dir=images_dir_path,
                pdfs_dir=pdfs_dir_path,
            )

        if result.get("reference"):
            print(
                f"  => final {result['reference']} | "
                f"{result['resolver_status']} | "
                f"pdf={result.get('preferred_pdf_kind') or '-'} | "
                f"download={result.get('download_status', 'sin_descarga')}"
            )

        final_results.append(result)

    result_df = pd.DataFrame(final_results)
    output_df = df.copy()

    for col in result_df.columns:
        if col in {"reference", "name"}:
            continue
        output_df[col] = result_df[col]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    output_df.to_excel(out_path, index=False)
    print_summary(output_df, out_path, download=download, pdfs_dir_path=pdfs_dir_path)

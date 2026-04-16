from __future__ import annotations
from src.core.text import (
clean_spaces as core_clean_spaces,
)
from src.providers.bosch.config import (
    DEFAULT_IMAGES_DIR,
    DEFAULT_PDFS_DIR,
)
from src.providers.bosch.media import attach_downloads
from src.providers.bosch.catalog import load_catalog_rows
from src.providers.bosch.resolver import resolve_reference
from src.providers.bosch.family import promote_family_tech_sheets
import argparse
from pathlib import Path
import pandas as pd

REF_ALIASES = [
    "referencia",
    "ref",
    "artpro",
    "supplier_ref",
    "codigo",
    "código",
    "codart",
]

NAME_ALIASES = [
    "nombre",
    "descripcion",
    "descripción",
    "description",
    "product_name",
    "articulo",
    "artículo",
]

def clean_spaces(value: str) -> str:
    return core_clean_spaces(value)

def pick_column(df: pd.DataFrame, aliases: list[str], required: bool = True) -> str:
    normalized = {core_clean_spaces(col).casefold(): col for col in df.columns}
    for alias in aliases:
        match = normalized.get(core_clean_spaces(alias).casefold())
        if match:
            return match
    if required:
        raise ValueError(f"No se encontró ninguna columna válida entre: {aliases}")

    return ""
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolver Bosch: imagen + ficha técnica/catálogo desde Bosch Home Comfort, con docs portal como fallback."
    )
    parser.add_argument("--excel", required=True, help="Ruta del Excel de entrada")
    parser.add_argument("--out", required=True, help="Ruta del Excel de salida")
    parser.add_argument(
        "--catalog-jsonl",
        default="data/output/bosch_catalog.jsonl",
        help="Ruta del catálogo JSONL Bosch ya scrapeado",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Descarga imagen y PDF resueltos a disco",
    )
    parser.add_argument(
        "--images-dir",
        default="data/output/images/bosch_resolved",
        help="Carpeta de descarga de imágenes resueltas",
    )
    parser.add_argument(
        "--pdfs-dir",
        default=DEFAULT_PDFS_DIR,
        help="Carpeta de descarga de PDFs resueltos",
    )
    return parser
def run_bosch_doc_resolver(
    *,
    excel: str,
    out: str,
    catalog_jsonl: str = "data/output/bosch_catalog.jsonl",
    download: bool = False,
    images_dir: str = DEFAULT_IMAGES_DIR,
    pdfs_dir: str = DEFAULT_PDFS_DIR,
) -> None:
    excel_path = Path(excel)
    out_path = Path(out)
    catalog_path = Path(catalog_jsonl)
    images_dir_path = Path(images_dir)
    pdfs_dir_path = Path(pdfs_dir)

    if not excel_path.exists():
        raise FileNotFoundError(f"No existe el Excel: {excel_path}")

    df = pd.read_excel(excel_path, dtype=str).fillna("")
    ref_col = pick_column(df, REF_ALIASES, required=True)
    name_col = pick_column(df, NAME_ALIASES, required=False)

    catalog_rows = load_catalog_rows(catalog_path)
    print(f"bosch_catalog_rows: {len(catalog_rows)} | catalog_path: {catalog_path}")

    results = []
    total = len(df)

    for idx, row in df.iterrows():
        reference = clean_spaces(row.get(ref_col, ""))
        name = clean_spaces(row.get(name_col, "")) if name_col else ""

        if not reference:
            result = {
                "resolver_status": "skipped_empty_reference",
                "reference": "",
                "name": name,
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
                "notes": "fila sin referencia",
            }
        else:
            print(f"[{idx + 1}/{total}] Resolviendo {reference} | {name}")
            result = resolve_reference(reference, name, catalog_rows)
            print(
                f"  -> provisional {result['resolver_status']} | "
                f"img={'si' if result['resolved_image_url'] else 'no'} | "
                f"pdf={result['preferred_pdf_kind'] or '-'}"
            )

        results.append(result)

    results = promote_family_tech_sheets(results)

    final_results = []
    for result in results:
        result = attach_downloads(
            result=result,
            reference=clean_spaces(result.get("reference", "")),
            name=clean_spaces(result.get("name", "")),
            download_enabled=download,
            images_dir=images_dir_path,
            pdfs_dir=pdfs_dir_path,
        )

        if result.get("reference"):
            print(
                f"  => final {result['reference']} | "
                f"{result['resolver_status']} | "
                f"pdf={result['preferred_pdf_kind'] or '-'} | "
                f"download={result['download_status']}"
            )

        final_results.append(result)

    results = final_results

    result_df = pd.DataFrame(results)

    output_df = df.copy()
    for col in result_df.columns:
        if col in {"reference", "name"}:
            continue
        output_df[col] = result_df[col]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    output_df.to_excel(out_path, index=False)

    print("\nResumen")
    print(f"  total_rows: {len(output_df)}")
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


def main() -> None:
    args = build_parser().parse_args()
    run_bosch_doc_resolver(
        excel=args.excel,
        out=args.out,
        catalog_jsonl=args.catalog_jsonl,
        download=args.download,
        images_dir=args.images_dir,
        pdfs_dir=args.pdfs_dir,
    )


if __name__ == "__main__":
    main()
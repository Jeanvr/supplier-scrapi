from pathlib import Path
import argparse
import json
import re

import pandas as pd


# =========================================================
# RUTAS BASE
# =========================================================
ROOT = Path(__file__).resolve().parent


# =========================================================
# HELPERS
# =========================================================
def normalize_ref(value) -> str:
    """Deja una referencia solo con dígitos."""
    if value is None:
        return ""
    text = str(value).strip()
    return re.sub(r"\D+", "", text)


def is_real_value(value) -> bool:
    """Evita que NaN cuente como valor real."""
    if pd.isna(value):
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def first_downloaded_path(results, base_folder: str) -> str:
    """Devuelve la primera ruta descargada por Scrapy."""
    if not results:
        return ""

    for item in results:
        path = item.get("path", "")
        if path:
            return f"{base_folder}/{path}"

    return ""


def build_media_status(row) -> str:
    """Resume el estado de media."""
    has_image = bool(False if pd.isna(row.get("has_image")) else row.get("has_image"))
    has_pdf = bool(False if pd.isna(row.get("has_pdf")) else row.get("has_pdf"))

    if has_image and has_pdf:
        return "pdf_e_imagen"
    if has_pdf:
        return "solo_pdf"
    if has_image:
        return "solo_imagen"
    return "sin_media"


# =========================================================
# CARGA DEL CATÁLOGO JSONL
# =========================================================
def load_catalog(jsonl_path: Path) -> pd.DataFrame:
    rows = []

    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            row = json.loads(line)

            images = row.get("images") or []
            files = row.get("files") or []
            image_urls = row.get("image_urls") or []
            file_urls = row.get("file_urls") or []

            rows.append(
                {
                    "matched_ref": row.get("supplier_ref", ""),
                    "norm_matched_ref": normalize_ref(row.get("supplier_ref", "")),
                    "catalog_name": row.get("name", ""),
                    "catalog_category": row.get("category", ""),
                    "source_url": row.get("source_url", ""),
                    "docs_url": row.get("docs_url", ""),
                    "image_url": row.get("image_url", ""),
                    "pdf_url": row.get("pdf_url", ""),
                    "image_count": len(images),
                    "pdf_count": len(files),
                    "has_image": bool(row.get("image_url")) or bool(images) or bool(image_urls),
                    "has_pdf": bool(row.get("pdf_url")) or bool(files) or bool(file_urls),
                    "local_image": first_downloaded_path(images, "data/output/images"),
                    "local_pdf": first_downloaded_path(files, "data/output/pdfs"),
                }
            )

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    # Si hay refs repetidas, nos quedamos con la mejor:
    # primero la que tenga PDF, luego imagen, luego más archivos
    df = (
        df.sort_values(
            by=["has_pdf", "has_image", "pdf_count", "image_count"],
            ascending=[False, False, False, False],
        )
        .drop_duplicates(subset=["norm_matched_ref"], keep="first")
        .reset_index(drop=True)
    )

    return df


# =========================================================
# MAIN
# =========================================================
def main():
    parser = argparse.ArgumentParser(
        description="Cruza un Excel de entrada con un catálogo scrapeado en JSONL."
    )
    parser.add_argument(
        "--excel",
        required=True,
        help="Ruta del Excel de entrada. Ej: data/input/Bosch-Orkli.xlsx",
    )
    parser.add_argument(
        "--jsonl",
        required=True,
        help="Ruta del catálogo JSONL. Ej: data/catalogs/bosch_catalog.jsonl",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Ruta del Excel final. Ej: data/output/reports/bosch_match_report.xlsx",
    )
    parser.add_argument(
        "--excel-ref-col",
        default="artpro",
        help="Columna del Excel con la referencia proveedor. Por defecto: artpro",
    )
    parser.add_argument(
        "--excel-name-col",
        default="nombre",
        help="Columna del Excel con el nombre. Por defecto: nombre",
    )
    parser.add_argument(
        "--excel-code-col",
        default="codart",
        help="Columna del Excel con el código interno. Por defecto: codart",
    )

    args = parser.parse_args()

    excel_path = ROOT / args.excel
    jsonl_path = ROOT / args.jsonl
    output_path = ROOT / args.out

    if not excel_path.exists():
        raise FileNotFoundError(f"No encuentro el Excel: {excel_path}")

    if not jsonl_path.exists():
        raise FileNotFoundError(f"No encuentro el JSONL: {jsonl_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------
    # 1) CARGAR EXCEL
    # -----------------------------------------------------
    df_excel = pd.read_excel(excel_path, dtype=str).fillna("")
    df_excel.columns = [str(c).strip() for c in df_excel.columns]

    required_cols = {args.excel_code_col, args.excel_name_col, args.excel_ref_col}
    missing = required_cols - set(df_excel.columns)
    if missing:
        raise ValueError(f"Faltan columnas en el Excel: {sorted(missing)}")

    df_excel["norm_input_ref"] = df_excel[args.excel_ref_col].map(normalize_ref)

    # -----------------------------------------------------
    # 2) CARGAR CATÁLOGO
    # -----------------------------------------------------
    df_catalog = load_catalog(jsonl_path)

    # -----------------------------------------------------
    # 3) MERGE
    # -----------------------------------------------------
    merged = df_excel.merge(
        df_catalog,
        how="left",
        left_on="norm_input_ref",
        right_on="norm_matched_ref",
    )

    # Importante: aquí evitamos el bug de NaN => "matched"
    merged["match_status"] = merged["matched_ref"].apply(
        lambda x: "matched" if is_real_value(x) else "not_found"
    )

    merged["media_status"] = merged.apply(build_media_status, axis=1)

    # -----------------------------------------------------
    # 4) ORDEN DE COLUMNAS
    # -----------------------------------------------------
    ordered_cols = [
        args.excel_code_col,
        args.excel_name_col,
        args.excel_ref_col,
        "norm_input_ref",
        "match_status",
        "matched_ref",
        "catalog_name",
        "catalog_category",
        "image_url",
        "pdf_url",
        "local_image",
        "local_pdf",
        "media_status",
        "source_url",
        "docs_url",
    ]

    existing_cols = [c for c in ordered_cols if c in merged.columns]
    remaining_cols = [c for c in merged.columns if c not in existing_cols]
    merged = merged[existing_cols + remaining_cols]

    # -----------------------------------------------------
    # 5) RESUMEN
    # -----------------------------------------------------
    summary = pd.DataFrame(
        [
            {"metric": "rows_excel", "value": len(df_excel)},
            {"metric": "rows_catalog", "value": len(df_catalog)},
            {"metric": "matched_rows", "value": int((merged["match_status"] == "matched").sum())},
            {"metric": "not_found_rows", "value": int((merged["match_status"] == "not_found").sum())},
            {"metric": "with_image", "value": int(merged["has_image"].fillna(False).sum())},
            {"metric": "with_pdf", "value": int(merged["has_pdf"].fillna(False).sum())},
            {
                "metric": "with_both",
                "value": int(
                    (
                        merged["has_image"].fillna(False)
                        & merged["has_pdf"].fillna(False)
                    ).sum()
                ),
            },
        ]
    )

    # -----------------------------------------------------
    # 6) EXPORTAR EXCEL
    # -----------------------------------------------------
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        merged.to_excel(writer, sheet_name="report", index=False)
        summary.to_excel(writer, sheet_name="summary", index=False)

    print()
    print("=" * 60)
    print("REPORTE GENERADO")
    print("=" * 60)
    print(f"Salida: {output_path}")
    print()
    print(summary.to_string(index=False))
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()

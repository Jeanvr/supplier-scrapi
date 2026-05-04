from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

from src.core.multi_provider_resolver import normalize_provider_key
from src.core.text import clean_spaces
from src.providers.loader import load_provider


DEFAULT_INPUT_EXCEL = "articles SS12 sense imatges i fitxes.xlsx"
DEFAULT_OUTPUT_EXCEL = "data/output/reports/ss12_multimarca.xlsx"
INPUT_RENAME_MAP = {
    "SS12": "codigo",
    "Unnamed: 1": "nombre",
    "Unnamed: 2": "referencia",
    "Unnamed: 3": "MARCA",
}
REQUIRED_COLUMNS = ("codigo", "nombre", "referencia", "MARCA")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Runner batch por marca que delega en provider_doc_resolver.py por cada grupo de MARCA."
    )
    parser.add_argument("--excel", default=DEFAULT_INPUT_EXCEL, help="Excel de entrada multimarca")
    parser.add_argument("--out", default=DEFAULT_OUTPUT_EXCEL, help="Excel final combinado")
    parser.set_defaults(download=True)
    parser.add_argument("--download", dest="download", action="store_true", help="Descarga imágenes y PDFs")
    parser.add_argument("--no-download", dest="download", action="store_false", help="No descarga imágenes ni PDFs")
    return parser


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", clean_spaces(value).casefold()).strip("_")
    return slug or "sin_marca"


def _extract_process_summary(stdout: str) -> list[str]:
    lines = [line.rstrip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return []

    for idx, line in enumerate(lines):
        if line.strip() == "Resumen":
            return lines[idx : idx + 8]

    return lines[-8:]


def _print_prefixed_block(lines: list[str], *, prefix: str) -> None:
    for line in lines:
        print(f"{prefix}{line}")


def load_input_dataframe(excel_path: Path) -> pd.DataFrame:
    if not excel_path.exists():
        raise FileNotFoundError(f"No existe el Excel: {excel_path}")

    df = pd.read_excel(excel_path, dtype=str).fillna("")

    rename_map: dict[str, str] = {}
    for source_col, target_col in INPUT_RENAME_MAP.items():
        if source_col in df.columns and target_col not in df.columns:
            rename_map[source_col] = target_col

    df = df.rename(columns=rename_map)

    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas requeridas tras renombrar: {missing}")

    normalized_df = df.copy()
    for column in REQUIRED_COLUMNS:
        normalized_df[column] = normalized_df[column].map(clean_spaces)

    normalized_df["_marca_group"] = normalized_df["MARCA"].map(lambda value: clean_spaces(value).casefold())
    return normalized_df


def build_brand_summary(brand_df: pd.DataFrame, *, brand_label: str, provider_key: str, status: str, message: str) -> dict:
    resolver_status = brand_df["resolver_status"] if "resolver_status" in brand_df.columns else pd.Series(dtype=str)
    return {
        "marca": brand_label,
        "provider": provider_key,
        "rows_in": len(brand_df),
        "rows_out": len(brand_df),
        "status": status,
        "message": message,
        "resolved_ficha_tecnica": int((resolver_status == "resolved_ficha_tecnica").sum()),
        "resolved_catalogo_producto": int((resolver_status == "resolved_catalogo_producto").sum()),
        "resolved_image_only": int((resolver_status == "resolved_image_only").sum()),
        "not_found": int((resolver_status == "not_found").sum()),
    }


def run_batch_provider_doc_resolver(*, excel: str, out: str, download: bool) -> None:
    repo_root = Path(__file__).resolve().parent
    excel_path = Path(excel)
    out_path = Path(out)

    df = load_input_dataframe(excel_path)
    print(f"Total filas entrada: {len(df)}")

    summary_rows: list[dict] = []
    successful_outputs: list[pd.DataFrame] = []

    with tempfile.TemporaryDirectory(prefix="batch_provider_doc_resolver_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)

        for _, group_df in df.groupby("_marca_group", sort=True):
            brand_label = clean_spaces(group_df["MARCA"].iloc[0])
            provider_key = normalize_provider_key(brand_label)
            input_rows = len(group_df)

            if not brand_label:
                print("\n[SIN_MARCA] Saltando filas sin MARCA")
                summary_rows.append(
                    {
                        "marca": "",
                        "provider": "",
                        "rows_in": input_rows,
                        "rows_out": 0,
                        "status": "missing_brand",
                        "message": "Fila(s) sin valor en MARCA",
                        "resolved_ficha_tecnica": 0,
                        "resolved_catalogo_producto": 0,
                        "resolved_image_only": 0,
                        "not_found": 0,
                    }
                )
                continue

            print(f"\n[{brand_label}] {input_rows} fila(s) -> provider `{provider_key or '-'}`")

            try:
                load_provider(provider_key)
            except Exception as exc:
                message = str(exc)
                print(f"  skip: {message}")
                summary_rows.append(
                    {
                        "marca": brand_label,
                        "provider": provider_key,
                        "rows_in": input_rows,
                        "rows_out": 0,
                        "status": "provider_not_supported",
                        "message": message,
                        "resolved_ficha_tecnica": 0,
                        "resolved_catalogo_producto": 0,
                        "resolved_image_only": 0,
                        "not_found": 0,
                    }
                )
                continue

            brand_slug = slugify(brand_label)
            temp_excel = temp_dir / f"{brand_slug}_input.xlsx"
            temp_output = temp_dir / f"{brand_slug}_output.xlsx"

            temp_input_df = group_df.drop(columns=["_marca_group"]).copy()
            temp_input_df.to_excel(temp_excel, index=False)

            cmd = [
                sys.executable,
                "provider_doc_resolver.py",
                "--provider",
                provider_key,
                "--excel",
                str(temp_excel),
                "--out",
                str(temp_output),
            ]
            if download:
                cmd.append("--download")

            print(f"  cmd: {' '.join(shlex.quote(part) for part in cmd)}")
            completed = subprocess.run(
                cmd,
                cwd=repo_root,
                capture_output=True,
                text=True,
            )

            summary_lines = _extract_process_summary(completed.stdout)
            if summary_lines:
                _print_prefixed_block(summary_lines, prefix="  | ")

            if completed.returncode != 0:
                print(f"  ERROR: provider_doc_resolver devolvió código {completed.returncode}")
                if completed.stderr.strip():
                    _print_prefixed_block(completed.stderr.strip().splitlines(), prefix="  ! ")
                summary_rows.append(
                    {
                        "marca": brand_label,
                        "provider": provider_key,
                        "rows_in": input_rows,
                        "rows_out": 0,
                        "status": "provider_failed",
                        "message": completed.stderr.strip() or f"exit_code={completed.returncode}",
                        "resolved_ficha_tecnica": 0,
                        "resolved_catalogo_producto": 0,
                        "resolved_image_only": 0,
                        "not_found": 0,
                    }
                )
                continue

            if not temp_output.exists():
                message = "No se generó el Excel temporal de salida"
                print(f"  ERROR: {message}")
                summary_rows.append(
                    {
                        "marca": brand_label,
                        "provider": provider_key,
                        "rows_in": input_rows,
                        "rows_out": 0,
                        "status": "missing_output",
                        "message": message,
                        "resolved_ficha_tecnica": 0,
                        "resolved_catalogo_producto": 0,
                        "resolved_image_only": 0,
                        "not_found": 0,
                    }
                )
                continue

            brand_output_df = pd.read_excel(temp_output, dtype=str).fillna("")
            brand_output_df["batch_brand"] = brand_label
            brand_output_df["batch_provider"] = provider_key
            successful_outputs.append(brand_output_df)

            summary_rows.append(
                build_brand_summary(
                    brand_output_df,
                    brand_label=brand_label,
                    provider_key=provider_key,
                    status="completed",
                    message="ok",
                )
            )
            print(f"  ok: {len(brand_output_df)} fila(s) añadidas al combinado")

    if successful_outputs:
        combined_df = pd.concat(successful_outputs, ignore_index=True)
    else:
        combined_df = df.drop(columns=["_marca_group"]).iloc[0:0].copy()

    summary_df = pd.DataFrame(summary_rows)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path) as writer:
        combined_df.to_excel(writer, sheet_name="results", index=False)
        summary_df.to_excel(writer, sheet_name="batch_summary", index=False)

    print("\nResumen batch")
    print(f"  marcas_total: {len(summary_df)}")
    print(f"  marcas_completadas: {(summary_df['status'] == 'completed').sum() if not summary_df.empty else 0}")
    print(f"  marcas_con_error: {(summary_df['status'] != 'completed').sum() if not summary_df.empty else 0}")
    print(f"  filas_salida: {len(combined_df)}")
    print(f"  output: {out_path}")


def main() -> None:
    args = build_parser().parse_args()
    run_batch_provider_doc_resolver(
        excel=args.excel,
        out=args.out,
        download=args.download,
    )


if __name__ == "__main__":
    main()

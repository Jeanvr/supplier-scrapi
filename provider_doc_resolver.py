from __future__ import annotations

import argparse

from src.core.excel_runner import run_excel_resolver
from src.providers.loader import load_provider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolver multimarca: imagen + ficha técnica/catálogo usando la configuración del proveedor."
    )
    parser.add_argument("--provider", required=True, help="Clave del proveedor. Ej: bosch")
    parser.add_argument("--excel", required=True, help="Ruta del Excel de entrada")
    parser.add_argument("--out", required=True, help="Ruta del Excel de salida")
    parser.add_argument("--catalog-jsonl", default="", help="Ruta del catálogo JSONL del proveedor")
    parser.add_argument("--download", action="store_true", help="Descarga imagen y PDF resueltos a disco")
    parser.add_argument("--images-dir", default="", help="Carpeta de descarga de imágenes resueltas")
    parser.add_argument("--pdfs-dir", default="", help="Carpeta de descarga de PDFs resueltos")
    return parser


def run_provider_doc_resolver(
    *,
    provider_key: str,
    excel: str,
    out: str,
    catalog_jsonl: str = "",
    download: bool = False,
    images_dir: str = "",
    pdfs_dir: str = "",
) -> None:
    provider = load_provider(provider_key)

    run_excel_resolver(
        excel=excel,
        out=out,
        catalog_jsonl=catalog_jsonl or provider["default_catalog_jsonl"],
        ref_aliases=provider["ref_aliases"],
        name_aliases=provider["name_aliases"],
        load_catalog_rows=provider["load_catalog_rows"],
        resolve_reference=provider["resolve_reference"],
        postprocess_results=provider.get("postprocess_results"),
        attach_downloads_fn=provider.get("attach_downloads_fn"),
        download=download,
        images_dir=images_dir or provider["default_images_dir"],
        pdfs_dir=pdfs_dir or provider["default_pdfs_dir"],
        catalog_label=provider.get("catalog_label", f"{provider['key']}_catalog_rows"),
    )


def main() -> None:
    args = build_parser().parse_args()
    run_provider_doc_resolver(
        provider_key=args.provider,
        excel=args.excel,
        out=args.out,
        catalog_jsonl=args.catalog_jsonl,
        download=args.download,
        images_dir=args.images_dir,
        pdfs_dir=args.pdfs_dir,
    )


if __name__ == "__main__":
    main()
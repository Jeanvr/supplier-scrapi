from __future__ import annotations

import argparse
from pathlib import Path

from src.providers.loader import load_provider


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Construye el catálogo JSONL de un proveedor."
    )
    parser.add_argument("--provider", required=True, help="Clave del proveedor. Ej: calpeda")
    parser.add_argument("--out", default="", help="Ruta del JSONL de salida")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    provider = load_provider(args.provider)

    build_catalog_fn = provider.get("build_catalog_fn")
    if build_catalog_fn is None:
        raise ValueError(f"El proveedor {args.provider} no implementa build_catalog_fn")

    out_path = Path(args.out or provider["default_catalog_jsonl"])
    count = build_catalog_fn(out_path)

    print(f"catalog_rows: {count}")
    print(f"output: {out_path}")


if __name__ == "__main__":
    main()
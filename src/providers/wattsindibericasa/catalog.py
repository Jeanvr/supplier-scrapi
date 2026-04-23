from __future__ import annotations

from pathlib import Path

from src.providers.simple_catalog import classify_document_kind, load_catalog_rows_for_brand


def load_catalog_rows(catalog_path: Path) -> list[dict]:
    return load_catalog_rows_for_brand(catalog_path, default_brand="wattsindibericasa")

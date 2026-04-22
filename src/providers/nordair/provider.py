from __future__ import annotations

from src.providers.nordair.catalog import load_catalog_rows
from src.providers.nordair.resolver import resolve_reference


PROVIDER = {
    "key": "nordair",
    "catalog_label": "nordair_catalog_rows",
    "default_catalog_jsonl": "data/catalogs/nordair_catalog.jsonl",
    "default_images_dir": "data/output/images/nordair_resolved",
    "default_pdfs_dir": "data/output/pdfs/nordair_resolved",
    "ref_aliases": [
        "referencia",
        "ref",
        "supplier_ref",
        "codigo",
        "código",
        "codart",
    ],
    "name_aliases": [
        "nombre",
        "descripcion",
        "descripción",
        "description",
        "product_name",
        "articulo",
        "artículo",
    ],
    "load_catalog_rows": load_catalog_rows,
    "resolve_reference": resolve_reference,
}

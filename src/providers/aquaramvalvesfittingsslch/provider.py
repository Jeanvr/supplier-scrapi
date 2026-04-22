from __future__ import annotations

from src.providers.aquaramvalvesfittingsslch.catalog import load_catalog_rows
from src.providers.aquaramvalvesfittingsslch.resolver import resolve_reference


PROVIDER = {
    "key": "aquaramvalvesfittingsslch",
    "catalog_label": "aquaramvalvesfittingsslch_catalog_rows",
    "default_catalog_jsonl": "data/catalogs/aquaramvalvesfittingsslch_catalog.jsonl",
    "default_images_dir": "data/output/images/aquaramvalvesfittingsslch_resolved",
    "default_pdfs_dir": "data/output/pdfs/aquaramvalvesfittingsslch_resolved",
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

from __future__ import annotations

from src.providers.acfix.catalog import load_catalog_rows
from src.providers.acfix.downloads import attach_downloads
from src.providers.acfix.resolver import resolve_reference


PROVIDER = {
    "key": "acfix",
    "catalog_label": "acfix_catalog_rows",
    "default_catalog_jsonl": "data/catalogs/acfix_catalog.jsonl",
    "default_images_dir": "data/output/images/acfix_resolved",
    "default_pdfs_dir": "data/output/pdfs/acfix_resolved",
    "ref_aliases": [
        "referencia",
        "ref",
        "supplier_ref",
        "codigo",
        "código",
        "codart",
        "reference",
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
    "attach_downloads_fn": attach_downloads,
}


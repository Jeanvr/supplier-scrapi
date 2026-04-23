from __future__ import annotations

from src.providers.simple_media import attach_downloads
from src.providers.standardhidraulicasau.catalog import load_catalog_rows
from src.providers.standardhidraulicasau.resolver import resolve_reference


PROVIDER = {
    "key": "standardhidraulicasau",
    "catalog_label": "standardhidraulicasau_catalog_rows",
    "default_catalog_jsonl": "data/catalogs/standardhidraulicasau_catalog.jsonl",
    "default_images_dir": "data/output/images/standardhidraulicasau_resolved",
    "default_pdfs_dir": "data/output/pdfs/standardhidraulicasau_resolved",
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
    "attach_downloads_fn": attach_downloads,
}

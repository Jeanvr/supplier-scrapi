from __future__ import annotations

from src.providers.metalgrupsa.catalog import load_catalog_rows
from src.providers.metalgrupsa.resolver import resolve_reference
from src.providers.simple_media import attach_downloads


PROVIDER = {
    "key": "metalgrupsa",
    "catalog_label": "metalgrupsa_catalog_rows",
    "default_catalog_jsonl": "data/catalogs/metalgrupsa_catalog.jsonl",
    "default_images_dir": "data/output/images/metalgrupsa_resolved",
    "default_pdfs_dir": "data/output/pdfs/metalgrupsa_resolved",
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

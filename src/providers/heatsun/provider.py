from __future__ import annotations

from src.providers.heatsun.catalog import load_catalog_rows
from src.providers.heatsun.downloads import attach_downloads
from src.providers.heatsun.resolver import resolve_reference


PROVIDER = {
    "key": "heatsun",
    "catalog_label": "heatsun_catalog_rows",
    "default_catalog_jsonl": "data/catalogs/heatsun_catalog.jsonl",
    "default_images_dir": "data/output/images/heatsun_resolved",
    "default_pdfs_dir": "data/output/pdfs/heatsun_resolved",
    "ref_aliases": [
        "referencia",
        "ref",
        "artpro",
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

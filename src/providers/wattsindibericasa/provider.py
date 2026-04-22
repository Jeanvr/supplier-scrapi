from __future__ import annotations

from src.providers.simple_downloads import attach_downloads
from src.providers.wattsindibericasa.catalog import load_catalog_rows
from src.providers.wattsindibericasa.resolver import resolve_reference


PROVIDER = {
    "key": "wattsindibericasa",
    "catalog_label": "wattsindibericasa_catalog_rows",
    "default_catalog_jsonl": "data/catalogs/wattsindibericasa_catalog.jsonl",
    "default_images_dir": "data/output/images/wattsindibericasa_resolved",
    "default_pdfs_dir": "data/output/pdfs/wattsindibericasa_resolved",
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

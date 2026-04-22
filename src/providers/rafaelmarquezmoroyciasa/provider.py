from __future__ import annotations

from src.providers.simple_downloads import attach_downloads
from src.providers.rafaelmarquezmoroyciasa.catalog import load_catalog_rows
from src.providers.rafaelmarquezmoroyciasa.resolver import resolve_reference


PROVIDER = {
    "key": "rafaelmarquezmoroyciasa",
    "catalog_label": "rafaelmarquezmoroyciasa_catalog_rows",
    "default_catalog_jsonl": "data/catalogs/rafaelmarquezmoroyciasa_catalog.jsonl",
    "default_images_dir": "data/output/images/rafaelmarquezmoroyciasa_resolved",
    "default_pdfs_dir": "data/output/pdfs/rafaelmarquezmoroyciasa_resolved",
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

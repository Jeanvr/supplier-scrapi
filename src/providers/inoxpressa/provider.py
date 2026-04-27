from __future__ import annotations

from src.providers.inoxpressa.downloads import attach_downloads
from src.providers.inoxpressa.catalog import load_catalog_rows
from src.providers.inoxpressa.resolver import resolve_reference


PROVIDER = {
    "key": "inoxpressa",
    "catalog_label": "inoxpressa_catalog_rows",
    "default_catalog_jsonl": "data/catalogs/inoxpressa_catalog.jsonl",
    "default_images_dir": "data/output/images/inoxpressa_resolved",
    "default_pdfs_dir": "data/output/pdfs/inoxpressa_resolved",
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

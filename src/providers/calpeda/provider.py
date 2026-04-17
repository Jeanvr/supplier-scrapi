from __future__ import annotations
from src.providers.bosch.media import attach_downloads
from src.providers.calpeda.catalog import build_catalog_jsonl, load_catalog_rows
from src.providers.calpeda.resolver import resolve_reference


PROVIDER = {
    "key": "calpeda",
    "catalog_label": "calpeda_catalog_rows",
    "default_catalog_jsonl": "data/output/calpeda_catalog.jsonl",
    "default_images_dir": "data/output/images/calpeda_resolved",
    "default_pdfs_dir": "data/output/pdfs/calpeda_resolved",
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
    "postprocess_results": None,
    "attach_downloads_fn": attach_downloads,
    "build_catalog_fn": build_catalog_jsonl,
}
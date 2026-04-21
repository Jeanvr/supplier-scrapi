from __future__ import annotations

from src.providers.bosch.catalog import load_catalog_rows
from src.providers.bosch.config import BRAND_KEY, DEFAULT_IMAGES_DIR, DEFAULT_PDFS_DIR
from src.providers.bosch.family import promote_family_tech_sheets
from src.providers.bosch.media import attach_downloads
from src.providers.bosch.resolver import resolve_reference

PROVIDER = {
    "key": BRAND_KEY,
    "catalog_label": "bosch_catalog_rows",
    "default_catalog_jsonl": "data/catalogs/bosch_catalog.jsonl",
    "default_images_dir": DEFAULT_IMAGES_DIR,
    "default_pdfs_dir": DEFAULT_PDFS_DIR,
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
    "postprocess_results": promote_family_tech_sheets,
    "attach_downloads_fn": attach_downloads,
}

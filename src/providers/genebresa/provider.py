from __future__ import annotations

from src.providers.genebresa.catalog import load_catalog_rows
from src.providers.genebresa.resolver import resolve_reference


PROVIDER = {
    "key": "genebresa",
    "catalog_label": "genebresa_catalog_rows",
    "default_catalog_jsonl": "data/catalogs/genebresa_catalog.jsonl",
    "default_images_dir": "data/output/images/genebresa_resolved",
    "default_pdfs_dir": "data/output/pdfs/genebresa_resolved",
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

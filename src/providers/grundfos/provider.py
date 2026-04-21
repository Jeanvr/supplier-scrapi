from __future__ import annotations

from src.providers.bosch.media import attach_downloads
from src.providers.grundfos.catalog import load_catalog_rows
from src.providers.grundfos.resolver import resolve_reference


PROVIDER = {
    "key": "grundfos",
    "catalog_label": "grundfos_catalog_rows",
    "default_catalog_jsonl": "data/output/grundfos_catalog.jsonl",
    "default_images_dir": "data/output/images/grundfos_resolved",
    "default_pdfs_dir": "data/output/pdfs/grundfos_resolved",
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

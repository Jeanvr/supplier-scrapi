"""Proveedor Ariston - STUB (no implementado aún).

Preparado para integración futura de Ariston.
"""

BRAND_KEY = "ariston"
DEFAULT_CATALOG_JSONL = "data/catalogs/ariston_catalog.jsonl"
DEFAULT_IMAGES_DIR = "data/output/images/ariston_resolved"
DEFAULT_PDFS_DIR = "data/output/pdfs/ariston_resolved"


def load_catalog_rows(path):
    """Cargador de catálogo de Ariston (placeholder)."""
    raise NotImplementedError("Ariston no está implementado todavía")


def resolve_reference(reference, name, catalog_rows):
    """Resolver de referencias de Ariston (placeholder)."""
    raise NotImplementedError("Ariston no está implementado todavía")


PROVIDER = {
    "key": BRAND_KEY,
    "catalog_label": "ariston_catalog_rows",
    "default_catalog_jsonl": DEFAULT_CATALOG_JSONL,
    "default_images_dir": DEFAULT_IMAGES_DIR,
    "default_pdfs_dir": DEFAULT_PDFS_DIR,
    "ref_aliases": ["referencia", "ref", "codigo", "código"],
    "name_aliases": ["nombre", "descripcion", "descripción"],
    "load_catalog_rows": load_catalog_rows,
    "resolve_reference": resolve_reference,
}

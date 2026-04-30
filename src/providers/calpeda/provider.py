from __future__ import annotations
from src.providers.calpeda.catalog import build_catalog_jsonl, load_catalog_rows
from src.providers.calpeda.downloads import attach_downloads
from src.providers.calpeda.pdf_support import annotate_pdf_support
from src.providers.calpeda.resolver import CALPEDA_TARIFA_GLOBAL_URL, resolve_reference


def _postprocess_results(results: list[dict]) -> list[dict]:
    original_pdf_urls = [str(result.get("preferred_pdf_url", "")) for result in results]
    processed = annotate_pdf_support(results)
    for result, original_pdf_url in zip(processed, original_pdf_urls):
        if (
            original_pdf_url == CALPEDA_TARIFA_GLOBAL_URL
            and "calpeda_tarifa_global_preferred" in str(result.get("notes", ""))
        ):
            result["preferred_pdf_url"] = CALPEDA_TARIFA_GLOBAL_URL
    return processed


PROVIDER = {
    "key": "calpeda",
    "catalog_label": "calpeda_catalog_rows",
    "default_catalog_jsonl": "data/catalogs/calpeda_catalog.jsonl",
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
    "postprocess_results": _postprocess_results,
    "attach_downloads_fn": attach_downloads,
    "build_catalog_fn": build_catalog_jsonl,
}

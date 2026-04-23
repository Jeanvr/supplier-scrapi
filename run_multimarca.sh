#!/bin/bash

echo "=== Resolviendo GRUNDFOS ==="
python3 provider_doc_resolver.py \
  --provider grundfos \
  --excel data/output/reports/grundfos_rows_check.xlsx \
  --catalog-jsonl data/catalogs/grundfos_catalog.jsonl \
  --out data/output/reports/demo_grundfos.xlsx \
  --download \
  --images-dir data/output/images/grundfos_resolved \
  --pdfs-dir data/output/pdfs/grundfos_resolved

echo "=== Resolviendo CALPEDA ==="
python3 provider_doc_resolver.py \
  --provider calpeda \
  --excel data/input/calpeda_review_ok.xlsx \
  --out data/output/reports/demo_calpeda.xlsx \
  --download \
  --images-dir data/output/images/calpeda_resolved \
  --pdfs-dir data/output/pdfs/calpeda_resolved

echo "=== MULTIMARCA COMPLETADO ==="


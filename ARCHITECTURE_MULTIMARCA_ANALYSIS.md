# Análisis Profundo: Sistema Multimarca de Resolución de Documentos

**Generado**: 23 abril 2026  
**Contexto**: Entender descarga de PDFs, trimming, estados compartidos y arquitectura general

---

## 1. FLUJO GENERAL Y ORQUESTACIÓN

```
┌─ batch_provider_doc_resolver.py (ENTRADA)
│  └─ Excel multimarca (SS12, nombre, referencia, MARCA)
│     ↓
│     ├─ normalize_provider_key() + groupby MARCA
│     └─ subprocess: provider_doc_resolver.py --provider {clave} per marca
│        ↓
│        ├─ run_excel_resolver() [RESOLUCIÓN]
│        └─ trim_catalog_fallbacks_in_excel() [POSTPROCESAMIENTO]
│           ↓
│        Excel resultado marca + columnas resolver_status, local_pdf, etc
│
└─ Merge Excel final (batch_summary + results sheets)
```

### Función Principal: `run_batch_provider_doc_resolver()`
**Ubicación**: `batch_provider_doc_resolver.py:121-280`

```python
def run_batch_provider_doc_resolver(*, excel: str, out: str, download: bool) -> None:
    # 1. Carga Excel multimarca y normaliza columnas
    df = load_input_dataframe(excel_path)
    
    # 2. Agrupa por marca
    for _, group_df in df.groupby("_marca_group", sort=True):
        brand_label = clean_spaces(group_df["MARCA"].iloc[0])
        provider_key = normalize_provider_key(brand_label)
        
        # 3. Ejecuta provider_doc_resolver.py en subprocess
        cmd = [
            sys.executable,
            "provider_doc_resolver.py",
            "--provider", provider_key,
            "--excel", str(temp_excel),
            "--out", str(temp_output),
        ]
        if download:
            cmd.append("--download")
        
        completed = subprocess.run(cmd, cwd=repo_root, capture_output=True)
        
        # 4. Recolecta resultados y resume
        brand_output_df = pd.read_excel(temp_output, dtype=str).fillna("")
        successful_outputs.append(brand_output_df)
    
    # 5. Combina todos los Excel y genera Excel final con 2 sheets
    combined_df = pd.concat(successful_outputs, ignore_index=True)
    with pd.ExcelWriter(out_path) as writer:
        combined_df.to_excel(writer, sheet_name="results", index=False)
        summary_df.to_excel(writer, sheet_name="batch_summary", index=False)
```

**Resumen genera** (batch_summary sheet):
```
marca | provider | rows_in | rows_out | status | resolved_ficha_tecnica | 
resolved_catalogo_producto | resolved_image_only | not_found
```

---

## 2. NÚCLEO DE RESOLUCIÓN: run_excel_resolver()

**Ubicación**: `src/core/excel_runner.py:81-166`

```python
def run_excel_resolver(
    *,
    excel: str,
    out: str,
    catalog_jsonl: str,
    ref_aliases: list[str],              # ["referencia", "ref", "codigo"]
    name_aliases: list[str],             # ["nombre", "descripcion"]
    load_catalog_rows: LoadCatalogRowsFn, # provider["load_catalog_rows"]
    resolve_reference: ResolverFn,       # provider["resolve_reference"]
    postprocess_results: PostprocessFn | None = None,
    attach_downloads_fn: AttachDownloadsFn | None = None,
    download: bool = False,
    images_dir: str,
    pdfs_dir: str,
) -> None:
    # 1. Carga Excel de entrada
    df = pd.read_excel(excel_path, dtype=str).fillna("")
    ref_col = pick_column(df, ref_aliases, required=True)
    name_col = pick_column(df, name_aliases, required=False)
    
    # 2. Carga catálogo del proveedor
    catalog_rows = load_catalog_rows(Path(catalog_jsonl))
    print(f"catalog_rows: {len(catalog_rows)} | catalog_path: {catalog_jsonl}")
    
    # 3. RESOLUCIÓN: para cada referencia, busca match en catálogo
    results = []
    for idx, row in df.iterrows():
        reference = clean_spaces(row.get(ref_col, ""))
        name = clean_spaces(row.get(name_col, "")) if name_col else ""
        
        if not reference:
            result = build_empty_result(name)
        else:
            # ⭐ FUNCIÓN CRITICAL: resolve_reference
            result = resolve_reference(reference, name, catalog_rows)
        
        results.append(result)
    
    # 4. POST-PROCESAMIENTO (si aplica)
    if postprocess_results is not None:
        results = postprocess_results(results)
    
    # 5. DESCARGA (si --download activado y attach_downloads_fn existe)
    final_results = []
    for result in results:
        if attach_downloads_fn is not None:
            # ⭐ FUNCIÓN CRITICAL: attach_downloads
            result = attach_downloads_fn(
                result=result,
                reference=clean_spaces(result.get("reference", "")),
                name=clean_spaces(result.get("name", "")),
                download_enabled=download,
                images_dir=Path(images_dir),
                pdfs_dir=Path(pdfs_dir),
            )
        
        final_results.append(result)
    
    # 6. Exporta Excel
    result_df = pd.DataFrame(final_results)
    output_df = df.copy()
    for col in result_df.columns:
        if col not in {"reference", "name"}:
            output_df[col] = result_df[col]
    
    output_df.to_excel(out_path, index=False)
```

**Columnas OUTPUT del Excel**:
```
[original columns] + resolver_status + resolved_image_url + preferred_pdf_url +
preferred_pdf_kind + matched_catalog_name + download_status + local_pdf + 
local_image + download_notes + ...
```

---

## 3. ESTADOS Y TRANSICIONES: resolver_status

### Determinación (en `resolve_reference()` de cada provider)

```python
# Ejemplo: genebresa/resolver.py:156-162
resolver_status = "not_found"
if pdf_kind == "ficha_tecnica" and pdf_url:
    resolver_status = "resolved_ficha_tecnica"
elif pdf_kind == "catalogo_producto" and pdf_url:
    resolver_status = "resolved_catalogo_producto"  # ⭐ CATALOGO COMPARTIDO
elif image_url:
    resolver_status = "resolved_image_only"
```

### Estados Posibles:
| Estado | Significado | PDF URL | Imagen | Origen |
|--------|-------------|---------|--------|--------|
| **resolved_ficha_tecnica** | Ficha técnica encontrada | ✓ (ficha) | ? | Catálogo match |
| **resolved_catalogo_producto** | Catálogo general encontrado | ✓ (catalogo) | ? | **Catálogo match → COMPARTIBLE** |
| **resolved_image_only** | Solo imagen sin PDF | ✗ | ✓ | Catálogo o fallback |
| **not_found** | Sin match o sin URLs | ✗ | ✗ | Búsqueda falló |
| **skipped_empty_reference** | Referencia vacía | ✗ | ✗ | Input error |

---

## 4. DESCARGA: attach_downloads()

**Ubicación**: `src/providers/bosch/media.py:108-198` (implementación de referencia)
**Reutilización**: `src/providers/simple_media.py` (usado por Genebresa, Teide, Aquaram, Tucaisa)

```python
def attach_downloads(
    result: dict,
    reference: str,
    name: str,
    download_enabled: bool,
    images_dir: Path,
    pdfs_dir: Path,
) -> dict:
    result["download_enabled"] = download_enabled
    result["download_status"] = "not_requested"
    result["local_image"] = ""
    result["local_pdf"] = ""
    result["download_notes"] = ""
    
    if not download_enabled:
        return result
    
    image_url = clean_spaces(result.get("resolved_image_url", ""))
    pdf_url = clean_spaces(result.get("preferred_pdf_url", ""))
    
    # ⭐ FUNCIÓN CRITICAL: Genera rutas locales ÚNICAS por referencia
    image_path_base, pdf_path = build_download_paths(
        reference=reference,
        name=name,
        preferred_pdf_kind=clean_spaces(result.get("preferred_pdf_kind", "")),
        preferred_pdf_url=pdf_url,
        resolved_image_url=image_url,
        images_dir=images_dir,
        pdfs_dir=pdfs_dir,
    )
    
    notes = []
    image_ok = False
    pdf_ok = False
    
    # 1. DESCARGA IMAGEN
    if image_url and image_path_base is not None:
        temp_path = image_path_base.with_suffix(".imgtmp")
        ok, final_url, content_type, error = download_binary(
            image_url, temp_path, accept_pdf=False
        )
        if ok:
            try:
                # Convierte a JPG ecommerce (1600x1600)
                final_image_path = save_ecommerce_jpg(temp_path, image_path_base)
                temp_path.unlink(missing_ok=True)
                result["local_image"] = str(final_image_path)
                result["downloaded_image_url"] = final_url
                image_ok = True
            except Exception as exc:
                temp_path.unlink(missing_ok=True)
                notes.append(f"image:convert_error:{exc}")
        else:
            temp_path.unlink(missing_ok=True)
            notes.append(f"image:{error or 'unknown_error'}")
    
    # 2. DESCARGA PDF
    if pdf_url and pdf_path is not None:
        ok, final_url, content_type, error = download_binary(
            pdf_url, pdf_path, accept_pdf=True
        )
        if ok:
            result["local_pdf"] = str(pdf_path)
            result["downloaded_pdf_url"] = final_url
            pdf_ok = True
        else:
            if pdf_path.exists():
                pdf_path.unlink(missing_ok=True)
            notes.append(f"pdf:{error or 'unknown_error'}")
    
    # 3. DETERMINA download_status
    if image_ok and pdf_ok:
        result["download_status"] = "downloaded_image_and_pdf"
    elif image_ok and not pdf_url:
        result["download_status"] = "downloaded_image_only"
    elif image_ok and pdf_url and not pdf_ok:
        result["download_status"] = "downloaded_image_pdf_failed"
    elif pdf_ok and not image_url:
        result["download_status"] = "downloaded_pdf_only"
    elif pdf_ok and image_url and not image_ok:
        result["download_status"] = "downloaded_pdf_image_failed"
    elif image_url or pdf_url:
        result["download_status"] = "download_failed"
    else:
        result["download_status"] = "nothing_to_download"
    
    result["download_notes"] = " | ".join(notes)
    return result
```

### Función Crítica: `build_download_paths()`

```python
def build_download_paths(
    reference: str,
    name: str,
    preferred_pdf_kind: str,
    preferred_pdf_url: str,
    resolved_image_url: str,
    images_dir: Path,
    pdfs_dir: Path,
) -> tuple[Path | None, Path | None]:
    # Extrae marca de la carpeta
    brand_part = _brand_from_dir(images_dir)  # "BOSCH", "GENEBRESA", etc
    
    # Normaliza referencia: slug sin guiones
    ref_part = slugify(reference, max_length=60).replace("-", "").upper()
    
    # ⭐ RUTAS ÚNICAS POR REFERENCIA
    image_path = images_dir / f"SS12_{brand_part}_{ref_part}_IMG"
    pdf_path = pdfs_dir / f"SS12_{brand_part}_{ref_part}_FT.pdf"
    
    return image_path, pdf_path
```

**Ejemplo de rutas generadas**:
- Referencia: "MPS630SS12" → Genebresa → `SS12_GENEBRESA_MPS630SS12_FT.pdf`
- Referencia: "VLA15DN32" → Tucaisa → `SS12_TUCAISA_VLA15DN32_FT.pdf`

---

## 5. PDF TRIMMING (ONLY TUCAISA)

**Ubicación**: `src/core/catalog_fallback_trimmer.py`

```python
TRIM_ENABLED_PROVIDERS = {"tucaisa"}  # ⭐ SOLO TUCAISA
CATALOG_PAGE_THRESHOLD = 20             # Mínimo páginas para trimming
MAX_REFERENCE_PAGES = 2                 # Máximo páginas a extraer

def trim_catalog_fallbacks_in_excel(excel_path: Path, *, provider_key: str | None = None) -> int:
    """
    Post-procesa Excel después de descarga:
    1. Filtra rows con resolved_catalogo_producto + batch_provider en TRIM_ENABLED_PROVIDERS
    2. Extrae 1-2 páginas relevantes por referencia
    3. Reemplaza local_pdf con PDF recortado
    4. Actualiza download_notes con info de trimming
    """
    workbook = pd.read_excel(excel_path, sheet_name=None, dtype=str)
    sheet_name = "results" if "results" in workbook else next(iter(workbook))
    df = workbook[sheet_name].fillna("")
    
    pages_cache: dict[Path, list[str]] = {}
    trimmed_count = 0
    
    for idx, row in df.iterrows():
        row_provider = clean_spaces(row.get("batch_provider", "")) or provider_key
        
        # 1. FILTROS
        if row_provider not in TRIM_ENABLED_PROVIDERS:
            continue
        if row.get("resolver_status") != "resolved_catalogo_producto":
            continue
        if row.get("preferred_pdf_kind") != "catalogo_producto":
            continue
        if "pdf:trimmed_catalog" in row.get("download_notes", ""):
            continue  # Ya fue recortado
        
        source_pdf = Path(clean_spaces(row.get("local_pdf", "")))
        if not source_pdf.exists():
            continue
        
        # 2. CARGA TEXTO DEL PDF (con caché)
        try:
            pages = pages_cache.get(source_pdf)
            if pages is None:
                pages = extract_pdf_text(source_pdf)
                pages_cache[source_pdf] = pages
        except Exception:
            continue
        
        if len(pages) <= CATALOG_PAGE_THRESHOLD:
            continue  # PDF muy pequeño, no trimea
        
        # 3. ELIGE PÁGINAS POR MATCHING
        reference_pages, matched_token = _choose_reference_pages(
            pages,
            reference=clean_spaces(row.get("referencia", "")),
            code=clean_spaces(row.get("codigo", "")),
            name=clean_spaces(row.get("nombre", "")),
            matched_name=clean_spaces(row.get("matched_catalog_name", "")),
        )
        if not reference_pages:
            continue
        
        # 4. INCLUYE SIEMPRE PÁGINA 1 + páginas encontradas
        final_pages = [1]
        for page in reference_pages:
            if page not in final_pages:
                final_pages.append(page)
        
        # 5. GENERA RUTA NUEVA RECORTADA
        output_pdf = _trimmed_pdf_path(
            source_pdf,
            row_provider,
            clean_spaces(row.get("codigo", "")),
            clean_spaces(row.get("referencia", "")),
        )
        # Ruta generada: data/output/pdfs/tucaisa_resolved/SS12_TUCAISA_CODIGO_FT.pdf
        
        # 6. RECORTA PÁGINAS Y SALVA
        try:
            merge_selected_pages(source_pdf, final_pages, output_pdf)
        except Exception:
            continue
        
        # 7. ACTUALIZA COLUMNAS
        df.at[idx, "local_pdf"] = str(output_pdf)
        trim_note = f"pdf:trimmed_catalog:{matched_token}:pages={','.join(str(p) for p in final_pages)}:source_pages={len(pages)}"
        if "download_notes" in df.columns:
            df.at[idx, "download_notes"] = _append_note(
                clean_spaces(row.get("download_notes", "")), trim_note
            )
        trimmed_count += 1
    
    # 8. GUARDA EXCEL MODIFICADO
    if trimmed_count:
        workbook[sheet_name] = df
        with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
            for name, sheet_df in workbook.items():
                sheet_df.to_excel(writer, sheet_name=name, index=False)
    
    return trimmed_count
```

### Heurística de Extracción: `_choose_reference_pages()`

```python
def _choose_reference_pages(
    pages: list[str],
    *,
    reference: str,
    code: str,
    name: str,
    matched_name: str,
) -> tuple[list[int], str]:
    # 1. BÚSQUEDA EXACTA: referencia o código
    for exact_value in (reference, code):
        exact_pages = find_reference_pages(exact_value, pages)
        if exact_pages:
            block = group_consecutive_pages(exact_pages)[0]
            return block[:MAX_REFERENCE_PAGES], exact_value
    
    # 2. BÚSQUEDA SEMÁNTICA: tokens de modelo
    name_for_tokens = matched_name or name
    name_tokens = _name_tokens(name_for_tokens)
    
    for model_token in _strong_model_tokens(name_for_tokens, name):
        model_pages = find_reference_pages(model_token, pages)
        scored_pages = [
            (page_num, _page_score(pages[page_num - 1], 
                                   model_token=model_token, 
                                   name_tokens=name_tokens))
            for page_num in model_pages
        ]
        good_pages = [p for p, score in scored_pages if score >= 36]
        if not good_pages:
            continue
        
        blocks = group_consecutive_pages(good_pages)
        blocks.sort(key=lambda block: (-sum(...), len(block), block[0]))
        return blocks[0][:MAX_REFERENCE_PAGES], model_token
    
    return [], ""

def _page_score(page_text: str, *, model_token: str, name_tokens: set[str]) -> int:
    page_norm = _normalize_text(page_text)
    
    # Validación base
    if model_token not in page_norm or _is_bad_page(page_text):
        return -1000
    
    # No es página dominada por otro modelo
    model_counts = {t: page_norm.count(t) for t in set(MODEL_TOKEN_RE.findall(page_norm))}
    if any(count > model_counts.get(model_token, 0) for t, count in model_counts.items() if t != model_token):
        return -1000
    
    score = 20
    
    # Bonus: token en primeras líneas
    if 0 <= page_norm.find(model_token) <= 1200:
        score += 12
    
    # Bonus: palabras contexto (MODELO, RACORERIA, PRESION, etc)
    for word in PRODUCT_CONTEXT_WORDS:
        if word in page_norm:
            score += 4
    
    # Bonus: tokens del nombre encontrados
    score += len(name_tokens & set(re.findall(r"[A-Z0-9]+", page_norm))) * 2
    
    # Bonus especial: tabla MODELO + RACORERIA
    if "MODELO" in page_norm and ("RACORERIA" in page_norm or "RACORERÍA" in page_norm):
        score += 8
    
    return score
```

---

## 6. ESTRUCTURA DE RESOLVERS: GENEBRESA, TEIDE, AQUARAM, STANDARD

Todas siguen patrón **catalog-based**:

### genebresa/resolver.py: `resolve_reference()`

```python
def resolve_reference(reference: str, name: str, catalog_rows: list[dict]) -> dict:
    reference = clean_spaces(reference)
    name = clean_spaces(name)
    
    if not catalog_rows:
        return _build_not_found(reference, name, "genebresa_catalog_empty")
    
    # 1. SCORING: cada fila de catálogo se puntúa
    ranked_rows = sorted(
        ((_score_row(reference, name, row), row) for row in catalog_rows),
        key=lambda item: item[0],
        reverse=True,
    )
    best_score, best_row = ranked_rows[0] if ranked_rows else (-1, None)
    
    # 2. FILTRO: score mínimo (160 para Genebresa/Aquaram, 120 para Teide)
    if best_row is None or best_score < 160:
        return _build_not_found(reference, name, "genebresa_no_catalog_match")
    
    # 3. EXTRAE DATOS DEL MATCH
    matched_name = clean_spaces(best_row.get("name", ""))
    matched_ref = clean_spaces(best_row.get("supplier_ref", ""))
    image_url = clean_spaces(best_row.get("image_url", ""))
    pdf_url = clean_spaces(best_row.get("pdf_url", ""))
    pdf_kind = classify_document_kind(best_row)  # "ficha_tecnica" o "catalogo_producto"
    pdf_title = clean_spaces(best_row.get("pdf_title", "")) or matched_name
    pdf_doc_type = clean_spaces(best_row.get("pdf_doc_type", "")) or pdf_kind
    
    # 4. DETERMINA resolver_status
    resolver_status = "not_found"
    if pdf_kind == "ficha_tecnica" and pdf_url:
        resolver_status = "resolved_ficha_tecnica"
    elif pdf_kind == "catalogo_producto" and pdf_url:
        resolver_status = "resolved_catalogo_producto"  # ⭐ CATALOGO GENERAL
    elif image_url:
        resolver_status = "resolved_image_only"
    
    # 5. CONSTRUYE RESULTADO
    return {
        "resolver_status": resolver_status,
        "reference": reference,
        "name": name,
        "matched_catalog_name": matched_name,
        "matched_catalog_ref": matched_ref,
        "matched_catalog_score": str(best_score),
        "product_page_url": clean_spaces(best_row.get("source_url", "")),
        "resolved_image_url": image_url,
        "preferred_pdf_kind": pdf_kind,
        "preferred_pdf_label": pdf_title if pdf_url else "",
        "preferred_pdf_url": pdf_url,  # ⭐ MISMA URL PARA MÚLTIPLES REFERENCIAS
        "preferred_doc_type": pdf_doc_type,
        "preferred_title": pdf_title if pdf_url else "",
        "notes": "genebresa_catalog_match",
    }
```

### Función Scoring: `_score_row()`

```python
def _score_row(reference: str, name: str, row: dict) -> int:
    score = 0
    
    # 1. MATCH EXACTO REFERENCIA
    ref_norm = _normalize(reference)
    ref_compact = _compact(reference)
    row_ref_norm = _normalize(row.get("supplier_ref", ""))
    row_ref_compact = _compact(row.get("supplier_ref", ""))
    
    if ref_norm == row_ref_norm:
        score += 100  # Match exacto
    elif ref_compact == row_ref_compact:
        score += 80   # Match compacto
    
    # 2. MATCH EXACTO NOMBRE
    name_norm = _normalize(name)
    name_compact = _compact(name)
    row_name_norm = _normalize(row.get("name", ""))
    row_name_compact = _compact(row.get("name", ""))
    
    if name_norm == row_name_norm:
        score += 500  # Match exacto nombre
    elif name_compact == row_name_compact:
        score += 450
    elif row_name_compact in name_compact or name_compact in row_name_compact:
        score += 180  # Partial match
    
    # 3. MATCH TOKEN
    query_tokens = set(_tokens(f"{reference} {name}"))
    row_tokens = set(_tokens(_search_blob(row)))
    score += len(query_tokens & row_tokens) * 25  # +25 por token matcheado
    
    # 4. BONUS: tiene PDF e imagen
    if row.get("pdf_url"):
        score += 20
    if row.get("image_url"):
        score += 10
    
    return score
```

### standardhidraulica (genérico via simple_catalog.py)

```python
# standardhidraulicasau/resolver.py
from src.providers.simple_catalog import make_resolver

resolve_reference = make_resolver(
    "standardhidraulicasau",
    extra_stopwords={"STANDARD", "HIDRAULICA", "SAU", "STH"},
)
```

---

## 7. EL CUELLO DE BOTELLA: PDFs COMPARTIDOS

### Problema

```
Genebresa catálogo: "https://genebre.es/catalogo_valvulas.pdf" (2.5 MB)
  ↓ usado por 100+ referencias de válvulas
  
Descarga actual:
- REF1 → SS12_GENEBRESA_VLA15DN32_FT.pdf (descarga copia 1)
- REF2 → SS12_GENEBRESA_VLA15DN50_FT.pdf (descarga copia 2)
- REF3 → SS12_GENEBRESA_VLA15DN80_FT.pdf (descarga copia 3)
  ...
- REF100 → SS12_GENEBRESA_VLA20DN150_FT.pdf (descarga copia 100)

Resultado: 100 copias del mismo PDF (250 MB en disco)
```

### Marcado en Excel

Fila 1: REF=VLA15DN32, preferred_pdf_url="https://genebre.es/catalogo_valvulas.pdf", 
        local_pdf="data/output/pdfs/genebresa_resolved/SS12_GENEBRESA_VLA15DN32_FT.pdf"

Fila 2: REF=VLA15DN50, preferred_pdf_url="https://genebre.es/catalogo_valvulas.pdf", 
        local_pdf="data/output/pdfs/genebresa_resolved/SS12_GENEBRESA_VLA15DN50_FT.pdf"

→ Columna preferred_pdf_url = **IGUAL** para todas
→ Columna local_pdf = **DIFERENTE** (ruta única por referencia)

### Por Qué Requiere Revisión Manual

1. **No hay deduplicación**: Sistema diseñado para crear ruta única por referencia
2. **No hay flag de compartir**: Sin columna que indique "PDF usado por N referencias"
3. **No hay detección de duplicados**: No checkea si ya existe esa URL en disco
4. **Ineficiencia con catálogos grandes**: Un PDF de 5 MB × 50 referencias = 250 MB
5. **Solo Tucaisa hace trimming**: Podría aprovechar reducir PDFs grandes

### Solución Manual Actual

- Revisor abre Excel
- Identifica filas con mismo preferred_pdf_url
- Copia manualmente local_pdf a 1 solo archivo
- Actualiza todas las referencias a apuntar al mismo archivo local
- Verifica que trimming de Tucaisa funcionó bien

### Alternativas Futuras

1. **Deduplicación en descarga**: Checkear si preferred_pdf_url ya fue descargado → link simbólico
2. **Expandir trimming**: Habilitar en Genebresa, Teide, Aquaram (config: TRIM_ENABLED_PROVIDERS)
3. **Marcar PDFs compartidos**: Nueva columna `pdf_shared_count` = número de referencias que usan la URL
4. **Consolidación post-descarga**: Script que busque PDFs idénticos (hash) y deduplicar

---

## 8. COMPARACIÓN: BOSCH vs GENEBRESA

### BOSCH: Sin catálogo JSONL
```
resolve_reference():
  1. find_best_catalog_row() en catálogo IN-MEMORY (bosch_catalog.py)
  2. Si match → resolve_from_product_page() → HTML scraping
  3. Fallback → resolve_from_docs_portal() → búsqueda web
  → Usualmente resolved_ficha_tecnica (datasheets individuales)
```

### GENEBRESA: Con catálogo JSONL
```
resolve_reference():
  1. _score_row() en catalog_rows[] (archivo JSONL descargado)
  2. Si match score >= threshold → extrae de row: pdf_url, pdf_kind
  3. classify_document_kind() → "ficha_tecnica" o "catalogo_producto"
  → Puede ser resolved_catalogo_producto (CATALOGO COMPARTIDO)
```

---

## 9. RESUMEN DE COLUMNAS FINALES

### Columnas de RESOLUCIÓN (entrada a attach_downloads)
```
resolver_status           → "resolved_ficha_tecnica" | "resolved_catalogo_producto" | ...
reference                 → Referencia original del input
name                       → Nombre original del input
matched_catalog_name      → Nombre matcheado del catálogo
matched_catalog_ref       → Referencia matcheada
matched_catalog_score     → Score del matching (0-1000+)
product_page_url          → URL de página de producto
resolved_image_url        → URL de imagen a descargar
preferred_pdf_kind        → "ficha_tecnica" | "catalogo_producto"
preferred_pdf_url         → ⭐ URL del PDF (puede ser compartida)
preferred_pdf_label       → Descripción del PDF
preferred_doc_type        → Tipo de documento
notes                      → Notas de resolución
```

### Columnas de DESCARGA (salida de attach_downloads)
```
download_enabled          → true/false
download_status           → "downloaded_image_and_pdf" | "download_failed" | ...
local_image               → Ruta local imagen descargada (SS12_MARCA_REF_IMG.jpg)
local_pdf                 → Ruta local PDF descargado (SS12_MARCA_REF_FT.pdf)
downloaded_image_url      → URL final después de redireccionamiento
downloaded_pdf_url        → URL final después de redireccionamiento
download_notes            → Errores/notas: "pdf:redirect_301 | image:convert_error:..."
```

### Columnas de TRIMMING (si aplica, actualiza local_pdf y download_notes)
```
local_pdf                 → ACTUALIZADO a ruta recortada
download_notes            → APPEND: "pdf:trimmed_catalog:TOKEN:pages=1,45,46:source_pages=256"
```

### Columnas BATCH (agregadas al combinar)
```
batch_brand               → Marca (de groupby original)
batch_provider            → Proveedor (genebresa, tucaisa, etc)
```

---

## 10. TABLAS DE REFERENCIA

### Providers y Statuses Que Generan

| Marca | Tipo Resolver | Genera ficha_tecnica | Genera catalogo_producto |
|-------|---------------|----------------------|--------------------------|
| Bosch | Portal + Docs | ✓ Sí (usual) | ✗ No |
| Genebresa | Catálogo JSONL | ✗ No | ✓ Sí (common) |
| Teide | Catálogo JSONL | ✗ No | ✓ Sí (common) |
| Aquaram | Catálogo JSONL | ✗ No | ✓ Sí (common) |
| Tucaisa | Catálogo JSONL | ✗ No | ✓ Sí (common) + **trimming** |
| Standard | simple_catalog | ✗ No | ✓ Sí (common) |
| Grundfos | ? | ? | ? |
| Calpeda | ? | ? | ? |

### Trimming Status

| Provider | Trimming | Threshold | Max Pages |
|----------|----------|-----------|-----------|
| Tucaisa | ✓ **ENABLED** | >20 pages | 2 |
| Otros | ✗ Disabled | - | - |

### Descargadores

| Provider | attach_downloads | Origen |
|----------|-----------------|--------|
| Bosch | custom | bosch/media.py |
| Genebresa | simple_media | reutilizado |
| Teide | simple_media | reutilizado |
| Aquaram | simple_media | reutilizado |
| Tucaisa | simple_media | reutilizado |
| Standard | simple_media | reutilizado |

---

## CONCLUSIONES

1. **Arquitectura escalable**: batch → provider → excel_runner → attach_downloads → trimming
2. **Estados claros**: resolver_status determina tipo de PDF encontrado
3. **Rutas únicas**: build_download_paths() garantiza SS12_MARCA_REF_FT.pdf único por (marca, ref)
4. **Compartición de catálogos**: Múltiples referencias → mismo PDF → múltiples copias en disco
5. **Trimming activo solo Tucaisa**: Reduce PDFs grandes a 1-2 páginas relevantes
6. **Deduplicación manual**: Requiere revisor humano post-descarga para consolidar PDFs compartidos
7. **Escalabilidad futura**: Expandir trimming, añadir deduplicación automática, flag PDFs compartidos

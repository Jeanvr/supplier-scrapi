# supplier-scrapi

## Objetivo
Proyecto de scraping multi-marca para ecommerce.
Prioridad actual:
1. mantener Bosch/Junkers estable
2. mejorar Calpeda
3. acelerar matching de imagen + PDF + clasificación final

## Cómo trabajar aquí
- Haz cambios pequeños y seguros.
- No hagas refactors grandes si no se piden.
- No rompas Bosch/Junkers.
- Antes de editar varios archivos, resume el plan en 3-5 líneas.
- Si tocas naming o columnas del Excel, dilo explícitamente.

## Reglas del proyecto
- Junkers se trata como Bosch.
- Priorizar ficha técnica en español; si no existe, usar inglés.
- Mantener nomenclatura:
  - SS12_MARCA_CODIGO_IMG
  - SS12_MARCA_CODIGO_FT
- No borrar data/output salvo que se pida.

## Al tocar resolvers
- Preserva estos estados:
  - resolved_ficha_tecnica
  - resolved_catalogo_producto
  - resolved_image_only
  - not_found
- Si refactorizas, no cambies comportamiento.
- Si tocas matching, compara antes/después por conteos.

## Validación obligatoria
- Primero prueba corta.
- Luego prueba completa si la corta sale bien.
- Resume siempre:
  - total_rows
  - resolved_ficha_tecnica
  - resolved_catalogo_producto
  - resolved_image_only
  - not_found
- Si hay descargas, comprueba naming final de imagen y PDF.

## Codex style
CAVEMAN ULTRA ACTIVE by default.

- Maximum compression.
- Telegraphic.
- Short answers.
- No filler.
- Prefer commands, diffs, exact files, exact checks.
- For code, commits, security, destructive actions, PDF processing, and risky changes: write normally when needed.
- User can say "normal mode" to deactivate this style.

## Uso con Codex
- Antes de implementar, inspeccionar archivos relevantes.
- Primero explicar plan mínimo en 3-5 líneas.
- No editar hasta tener claro el alcance.
- Cambios pequeños y revisables.
- Un solo provider por iteración.
- Después de editar, mostrar:
  - archivos tocados
  - resumen del cambio
  - comandos de validación
  - métricas before/after si aplica
- Si algo no está claro, no inventar: pedir dato o proponer prueba corta.
- No hacer cambios globales para arreglar un provider salvo necesidad real.

## Anti-sobreingeniería
- No crear arquitecturas nuevas sin pedirlo.
- No añadir dependencias sin justificarlo.
- No cambiar nombres de columnas ni naming de archivos sin avisar antes.
- No tocar scripts batch/core si se puede resolver en el provider.
- Preferir parche pequeño a solución perfecta grande.

## Calpeda enfoque actual
- Web Calpeda no es fuente principal: puede traer productos parecidos pero no exactos.
- Prioridad actual: usar catálogo/tarifa PDF por referencia exacta.
- Tarifa global actual:
  - https://www.calpeda.com/wp-content/uploads/2025/03/CALPEDA-Catalogo-Tarifa-B19-marzo-2025-WEB.pdf
- Buscar referencia exacta en PDF de tarifa/catálogo.
- Generar PDF final desde la página o familia donde aparece la referencia.
- Máximo 3 páginas para family-crop.
- Quitar/ocultar precios de proveedor antes de guardar el PDF final.
- Mejor PDF de tarifa correcto y sin precios que ficha web dudosa.
- Mejor dejar imagen vacía que asignar una imagen incorrecta.
- Usar `resolved_catalogo_producto` para tarifa global.
- Marcar en notes/download_notes:
  - `calpeda_tarifa_global_candidate`
  - `calpeda_tarifa_global_preferred`
  - `calpeda_tarifa_ref_exact`
  - `price_removed`
  - `calpeda_family_crop`
  - `calpeda_family_pages=...`
  - `calpeda_pdf_ref_not_exact`
- No romper estados existentes:
  - `resolved_ficha_tecnica`
  - `resolved_catalogo_producto`
  - `resolved_image_only`
  - `not_found`

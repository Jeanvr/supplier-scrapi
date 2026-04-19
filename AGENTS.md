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
Calpeda:
- Prioridad actual: aceptar datasheet EN como ficha técnica válida cuando no exista evidencia real de ficha equivalente en ES.
- No invertir tiempo en priorización ES en catalog.py sin evidencia concreta de URLs técnicas ES individuales.
- No priorizar catálogos mixtos 60Hz English/Español por delante de datasheet_EN.
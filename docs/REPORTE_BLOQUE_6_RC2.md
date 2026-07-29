# Elegance Cloud 2 RC2 — Bloque 6

## Objetivo
Completar el flujo visual móvil de productos sin depender todavía de una cuenta externa: carga múltiple, conservación del original, deduplicación exacta, variantes de salida, portada y recuperación ante fallos.

## Funciones implementadas

- Carga múltiple autenticada desde navegador móvil o escritorio.
- Asociación obligatoria de cada lote con un producto.
- Asociación opcional con una variante de talla/color.
- Detección de duplicados por SHA-256 antes de procesar.
- Estados: `queued`, `processing`, `ready`, `failed`.
- Conservación del archivo original.
- Generación WebP de:
  - catálogo (máximo 1600 × 1600),
  - miniatura (máximo 480 × 480),
  - WhatsApp (máximo 1080 × 1080).
- Compatibilidad con almacenamiento `local`, `supabase` y `mirror`.
- Selección de portada y sincronización con la ficha heredada del producto.
- Reasignación de imagen a una variante.
- Reintento usando la copia original local.
- Eliminación protegida por confirmación; si se elimina la portada se asigna otra imagen lista.
- Interfaz integrada en `catalog-admin.html`, adaptable a teléfono.

## Endpoints añadidos

- `POST /api/admin/catalog/products/{product_id}/images/batch`
- `GET /api/admin/catalog/products/{product_id}/images`
- `PUT /api/admin/catalog/products/{product_id}/images/{asset_id}/cover`
- `PUT /api/admin/catalog/products/{product_id}/images/{asset_id}/variant`
- `POST /api/admin/catalog/images/{asset_id}/retry`
- `DELETE /api/admin/catalog/products/{product_id}/images/{asset_id}?confirm=true`

## Persistencia

Se añadieron las tablas:

- `product_media_assets`
- `product_media_outputs`

No se eliminan ni reemplazan las tablas heredadas. La migración es idempotente.

## Verificación

- Compilación Python: correcta.
- Pruebas automáticas: 12 aprobadas.
- Casos cubiertos:
  - creación de cuatro salidas,
  - portada automática,
  - deduplicación,
  - cambio de portada,
  - asociación de variante,
  - eliminación con confirmación,
  - reasignación automática de portada.

## Limitación actual

La edición inteligente del fondo y el reconocimiento visual avanzado pertenecen al Bloque 7. En este bloque las variantes se redimensionan y convierten, pero no se inventa ni altera el escenario del producto.

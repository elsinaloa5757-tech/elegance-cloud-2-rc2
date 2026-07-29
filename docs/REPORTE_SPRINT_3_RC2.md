# Elegance Platform — Sprint 3 RC2

## Inventario Inteligente

- Diagnóstico general de salud del inventario.
- Calidad y completitud por producto (0–100).
- Estados: Excelente, Bueno, Incompleto y Crítico.
- Detección de stock agotado y stock bajo.
- Detección de campos faltantes.
- Detección de duplicados por imagen exacta, SKU y similitud de identidad.
- Fusión segura en dos pasos: vista previa y confirmación.
- Respaldo automático antes de fusionar.
- Historial auditable de fusiones.
- Migración aditiva que conserva IDs, imágenes, precios, tallas, stock, notas y fechas.
- SQLite optimizado con WAL, synchronous NORMAL e índices de auditoría.

## Endpoints

- `GET /api/inventory/health`
- `GET /api/inventory/duplicates`
- `POST /api/inventory/migrate`
- `POST /api/inventory/merge`
- `GET /api/inventory/audit`

## Seguridad

La fusión nunca se ejecuta sin `confirm: true`. Antes de cualquier fusión se conserva una copia completa del estado en `inventory_backups`.

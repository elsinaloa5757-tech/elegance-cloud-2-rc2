# Elegance Platform — Sprint 3 RC4

## Elegance Studio

Se integró un flujo local-first, reversible y no destructivo para preparar imágenes de producto.

### Protección de datos
- Cada carga se copia primero al repositorio `data/studio/originals`.
- Las vistas previas se almacenan separadas de los originales.
- Ninguna vista previa se publica sin aprobación explícita.
- Rechazar o regenerar no altera la fotografía original.
- El historial SQLite conserva activo, versión, opciones, salidas, estado y restauraciones.

### Procesamiento
- eliminación de fondo mediante `rembg` cuando está disponible;
- alternativa local determinista para fondos uniformes;
- recorte por transparencia, centrado, corrección de brillo, contraste, color y nitidez;
- fondo premium Elegance azul hielo, fondo original o transparencia;
- sombra de contacto moderada;
- salidas de catálogo, miniatura, WhatsApp, Facebook, Instagram, Marketplace, vertical y horizontal;
- WEBP, JPG y PNG con calidad configurable;
- detección SHA-256 de imágenes duplicadas;
- procesamiento individual y por lotes de hasta 100 archivos.

### API
- `POST /api/studio/migrate`
- `POST /api/studio/preview`
- `POST /api/studio/batch`
- `POST /api/studio/decide/{version_id}`
- `POST /api/studio/restore/{version_id}`
- `GET /api/studio/history`
- `GET /studio`

### Validación
- compilación Python completa;
- creación de vistas previas en múltiples tamaños;
- aprobación y copia a repositorio publicado;
- restauración de versión aprobada;
- detección de duplicado exacto;
- comprobación de que el original permanece intacto.

### Consideración técnica
La eliminación de fondo más precisa usa el paquete local `rembg`, ya incluido en `requirements.txt`. Cuando su modelo no está instalado, el sistema utiliza una alternativa local segura para fondos uniformes sin depender de servicios de pago.

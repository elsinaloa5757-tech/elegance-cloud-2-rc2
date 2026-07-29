# Elegance Platform — Sprint 4 RC2

## Portal de Ventas y Catálogo Público

Versión: 4.2.0-rc2

### Alcance implementado

- Catálogo público responsive en `/catalog`.
- Panel administrativo de publicación y solicitudes en `/catalog-admin`.
- Estados de publicación: borrador, publicado, oculto y agotado.
- Publicación individual y por lotes.
- Sincronización automática de productos existentes sin modificar inventario.
- Búsqueda y filtros por texto, categoría, subcategoría, marca, talla, color, disponibilidad y destacados.
- Vista individual y enlace permanente por slug en `/catalog/product/{slug}`.
- Imágenes aprobadas de Elegance Studio como fuente prioritaria.
- Carrito persistente mediante almacenamiento local del navegador.
- Captura de cliente, WhatsApp, entrega o envío, dirección y referencias.
- Registro o detección automática del cliente por teléfono/WhatsApp.
- Solicitudes comerciales idempotentes sin reservar ni descontar stock.
- Confirmación administrativa que convierte la solicitud en pedido comercial y entonces reserva inventario.
- Rechazo administrativo sin afectar existencias.
- Mensaje de WhatsApp con productos, tallas, colores, cantidades y total estimado.
- Analítica local de visitas, vistas de producto, carritos, solicitudes y origen/campaña.
- Arquitectura local y gratuita preparada para publicación web y pagos futuros.

### Endpoints principales

- `GET /catalog`
- `GET /catalog-admin`
- `GET /catalog/product/{slug}`
- `GET /api/public/products`
- `GET /api/public/products/{identifier}`
- `POST /api/public/requests`
- `POST /api/public/events`
- `GET /api/admin/publications`
- `PATCH /api/admin/publications/{product_id}`
- `POST /api/admin/publications/bulk`
- `GET /api/admin/requests`
- `POST /api/admin/requests/{identifier}/confirm`
- `POST /api/admin/requests/{identifier}/reject`
- `GET /api/public/dashboard`

### Seguridad de inventario

El catálogo público nunca modifica inventario ni confirma una venta. Una solicitud valida disponibilidad informativa pero conserva el stock. Solo la confirmación administrativa crea un pedido en el módulo comercial existente, donde se aplica la reserva transaccional. La idempotencia evita solicitudes y pedidos duplicados por reintentos de red.

### Validación ejecutada

- Compilación completa del backend.
- Migración SQLite.
- Sincronización de productos.
- Publicación de prueba.
- Búsqueda pública combinada.
- Creación de solicitud sin cambio de stock.
- Conversión a pedido con descuento correcto.
- Confirmación repetida sin pedido duplicado.
- Cancelación con devolución correcta del inventario.
- Limpieza de datos sintéticos.
- Verificación de integridad del ZIP.

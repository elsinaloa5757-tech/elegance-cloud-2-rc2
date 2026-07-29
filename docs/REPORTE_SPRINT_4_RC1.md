# Elegance Platform — Sprint 4 RC1

## Automatización Comercial

Esta versión incorpora gestión local y gratuita de clientes, pedidos, apartados, pagos, entregas, envíos y mensajes preparados para WhatsApp.

### Seguridad e inventario

- Respaldo automático antes de migraciones y cambios que afectan existencias.
- Validación de stock antes de confirmar, apartar o pagar.
- Descuento de existencia una sola vez mediante `stock_reserved`.
- Reposición automática al cancelar, salvo pedidos ya entregados.
- `idempotencyKey` para prevenir ventas duplicadas por reintentos de red.
- Conservación del estado, productos, imágenes, IA y versiones de Studio.

### Estados

`draft`, `pending`, `layaway`, `paid`, `prepared`, `shipped`, `delivered`, `cancelled`.

### API principal

- `POST /api/commercial/migrate`
- `POST/GET /api/customers`
- `POST/GET /api/orders`
- `GET /api/orders/{id}`
- `POST /api/orders/{id}/status`
- `POST /api/orders/{id}/payments`
- `GET /api/orders/{id}/receipt`
- `GET /api/orders/{id}/whatsapp`
- `GET /api/commercial/dashboard`
- `GET /api/commercial/audit`
- Interfaz: `/commercial`

### WhatsApp

Genera enlaces `wa.me` con cliente, folio, productos, talla, total, pagos, saldo, entrega o envío y guía. No requiere API de pago. La generación está desacoplada para permitir integrar posteriormente WhatsApp Business API sin reemplazar pedidos ni plantillas.

### Validación

Se verificó compilación Python, migración SQLite, alta y búsqueda de clientes, pedido con apartado, descuento de stock, pago parcial, saldo, enlace WhatsApp, cancelación, devolución de stock y limpieza de datos de prueba.

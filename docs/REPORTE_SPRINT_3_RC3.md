# Elegance Platform — Sprint 3 RC3

## Elegance AI
Motor local-first de sugerencias para identificación y publicación. No altera productos al analizar: toda sugerencia queda pendiente hasta confirmación explícita.

### Funciones
- Marca, modelo, nombre completo, categoría, subcategoría, género, colores y temporada.
- Descripción comercial, palabras clave y etiquetas.
- Confianza por campo y confianza general.
- Contradicciones entre datos actuales y sugeridos.
- Revisión responsive en `/ai` para teléfono y computadora.
- Confirmación manual obligatoria mediante `/api/ai/confirm`.
- Aprendizaje local a partir de correcciones.
- Historial SQLite de sugerencias y confirmaciones.
- Preservación forzada de ID, imágenes, stock, precio, tallas, notas y fecha.
- Sin dependencia obligatoria de IA de pago.

### Endpoints
- `POST /api/ai/migrate`
- `POST /api/ai/suggest/{product_id}`
- `POST /api/ai/confirm`
- `GET /api/ai/history`
- `GET /ai`

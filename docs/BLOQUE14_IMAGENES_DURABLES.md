# Bloque 14 — Imágenes durables

## Resultado

Las fotografías recibidas desde el teléfono se registran por SHA-256 y el
original se copia al bucket privado `elegance-private` antes de autorizar su
eliminación del dispositivo.

La interfaz móvil distingue dos estados:

- **Nube verificada:** el original coincide con su SHA-256 remoto y ya puede
  borrarse del teléfono.
- **Respaldo pendiente:** la copia local continúa en cola y no debe borrarse
  todavía.

## Arquitectura

- Originales y ediciones internas: `elegance-private`.
- Versiones web y miniaturas publicadas: `elegance-public`.
- Manifiesto verificable: `public.elegance_storage_objects`.
- Acceso a Storage: exclusivamente mediante la función protegida
  `elegance-sync`; la clave de servicio no se expone al navegador.
- Restauración: descarga privada mediante la función, validación SHA-256 y
  reemplazo atómico del archivo local.

## Operación

1. El teléfono envía una fotografía.
2. El servidor calcula SHA-256 y conserva una copia local temporal.
3. `elegance-sync` crea el bucket privado si aún no existe, sube el original y
   registra el manifiesto.
4. Solo tras recibir la confirmación con el mismo SHA-256 se muestra
   `Ya puedes borrarlo del teléfono`.
5. El análisis, las miniaturas y la publicación pueden continuar después sin
   poner en riesgo el original.

## Validación

- Duplicación por hash.
- Respuesta segura ante falla de red.
- Persistencia del estado remoto en SQLite.
- Descargas grandes codificadas por bloques.
- 36 pruebas automatizadas aprobadas.

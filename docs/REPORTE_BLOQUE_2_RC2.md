# Elegance Cloud 2 RC2 — Bloque 2

## Alcance terminado

- Preparación de esquema privado `elegance` para PostgreSQL/Supabase.
- Migrador genérico SQLite → PostgreSQL para todas las tablas existentes.
- Ejecución repetible mediante `--truncate` o inserción idempotente por claves existentes.
- Manifiesto de migración con conteos y hashes lógicos por tabla.
- Verificación posterior de filas y contenido canónico.
- Comprobación de conexión PostgreSQL sin revelar usuario, contraseña ni URL completa.
- Producción bloqueada si falta `DATABASE_URL`, almacenamiento persistente, HTTPS o CORS público.
- Endpoint administrativo `/api/system/cloud-database`.

## Estado real

El código para migrar y verificar está terminado y probado en modo seco contra la base incluida. La migración real no se ejecutó porque aún no existe una `DATABASE_URL` de Supabase autorizada en este entorno. La aplicación conserva SQLite como motor operativo hasta que la copia real pase la verificación completa; esto evita una transición destructiva o pérdida de información.

## Autorización necesaria para el siguiente paso

Crear o conectar el proyecto Supabase definitivo y proporcionar las variables únicamente en el proveedor de despliegue:

- `DATABASE_URL` (conexión PostgreSQL de servidor)
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` (solo backend)
- `SUPABASE_PUBLISHABLE_KEY` (frontend cuando corresponda)

Nunca deben subirse al repositorio ni incluirse en el ZIP.

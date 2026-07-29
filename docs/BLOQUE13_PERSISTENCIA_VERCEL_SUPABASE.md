# Bloque 13 — Persistencia Vercel + Supabase

Este bloque conserva la base SQLite completa de Elegance dentro de PostgreSQL
sin reescribir los módulos comerciales existentes.

## Funcionamiento

1. Cada operación dinámica abre una transacción PostgreSQL.
2. Adquiere un bloqueo transaccional exclusivo para `main`.
3. Restaura la última instantánea SQLite verificada por SHA-256.
4. Ejecuta normalmente los módulos actuales de Elegance.
5. Hace `wal_checkpoint`, guarda la base completa y aumenta la revisión.
6. Libera automáticamente el bloqueo al confirmar o revertir la transacción.

Los recursos estáticos y `/health` no toman el bloqueo.

## Producción serverless

Configurar en Vercel:

- `ELEGANCE_ENV=production`
- `ELEGANCE_SERVER_MODE=cloud`
- `ELEGANCE_DATA_DIR=/tmp/elegance`
- `DATABASE_URL`: conexión **Transaction pooler** de Supabase, puerto `6543`

La conexión debe usar SSL y no debe almacenarse en GitHub.

## Seguridad

La tabla `elegance_private.runtime_databases`:

- tiene RLS habilitado;
- no concede acceso a `anon` ni `authenticated`;
- se usa solamente desde la conexión privada del servidor;
- valida tamaño y SHA-256 antes de restaurar;
- serializa escrituras con `pg_advisory_xact_lock`.

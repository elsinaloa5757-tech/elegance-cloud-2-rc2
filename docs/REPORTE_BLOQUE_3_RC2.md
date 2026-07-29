# Elegance Cloud 2 RC2 — Bloque 3

## Objetivo
Dejar el backend listo para un primer despliegue público verificable sin publicar secretos ni declarar una URL inexistente.

## Cambios
- Endpoint `GET /api/system/deployment-readiness`.
- Validación de URL pública, CORS HTTPS, volumen escribible, Supabase y PostgreSQL.
- Docker ejecutándose como usuario no privilegiado.
- `HEALTHCHECK` integrado.
- Blueprint de Render con secretos externos y disco persistente.
- Flujo de GitHub Actions para compilación, pruebas y construcción Docker.
- Pruebas automatizadas del estado de despliegue.

## Criterio de URL pública
La URL solamente se considera válida cuando el proveedor confirme el despliegue y estos endpoints respondan:
- `/api/system/status`
- `/api/system/deployment-readiness`
- `/docs`
- `/catalog`

## Pendiente externo
- Autorizar un proyecto Supabase.
- Configurar `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` y `SUPABASE_SERVICE_ROLE_KEY` en el proveedor.
- Autorizar un proveedor con ejecución persistente de contenedores.

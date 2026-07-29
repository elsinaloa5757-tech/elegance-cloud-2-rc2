# Elegance Cloud 2 RC2 — Bloque 4

## Objetivo

Completar lo posible antes de conectar cuentas externas: abstracción de almacenamiento, configuración móvil pública, carga segura de archivos y diagnóstico integral de activación.

## Implementado

- Servicio `services/cloud_storage.py` con modos:
  - `local`: disco persistente.
  - `supabase`: Supabase Storage.
  - `mirror`: copia local y copia en Supabase.
- Sanitización de rutas para impedir traversal.
- Límite configurable mediante `ELEGANCE_MAX_UPLOAD_MB`.
- Hash SHA-256 de cada archivo guardado.
- Subida a Supabase únicamente desde backend con `SUPABASE_SERVICE_ROLE_KEY`.
- La clave administrativa no aparece en respuestas.
- Endpoint autenticado `POST /api/storage/upload`.
- Endpoint autenticado `GET /api/system/storage`.
- Endpoint público `GET /api/public/config` para web y aplicación móvil.
- Diagnóstico de despliegue ampliado con comprobación de almacenamiento cloud.
- Script `scripts/check_activation.py` para validar base, storage y despliegue.

## Variables nuevas

```env
ELEGANCE_STORAGE_MODE=mirror
SUPABASE_STORAGE_BUCKET=elegance-products
ELEGANCE_MAX_UPLOAD_MB=25
```

## Pruebas

- Compilación Python completa: correcta.
- Pytest: 7 pruebas aprobadas.
- Escritura local y lectura del archivo: correcta.
- Configuración pública accesible: correcta.
- Verificación de no exposición de secretos: correcta.

## Pendiente externo

No se creó una URL pública porque todavía no están conectadas las cuentas de Supabase y del proveedor de despliegue. El código ya puede activarse sin cambios estructurales al proporcionar las variables reales.

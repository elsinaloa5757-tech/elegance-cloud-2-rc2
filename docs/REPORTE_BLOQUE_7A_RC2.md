# Elegance Cloud 2 RC2 — Bloque 7A

## Objetivo
Convertir Elegance en una aplicación operable desde una computadora Windows propia, sin renta obligatoria de VPS, con persistencia, arranque automático, diagnóstico y respaldos verificables.

## Implementado

- Modo `ELEGANCE_SERVER_MODE=home` para producción doméstica.
- Persistencia mediante `ELEGANCE_DATA_DIR` y `ELEGANCE_SQLITE_PATH`.
- PostgreSQL local opcional mediante `DATABASE_URL`; SQLite permanece como modo inicial compatible.
- Programador interno de respaldos diarios y semanales.
- Copia automática opcional a segundo disco o unidad de red mediante `ELEGANCE_EXTERNAL_BACKUP_DIR`.
- Respaldo ZIP completo con manifiesto SHA-256 e integridad SQLite.
- Copia preventiva antes de restaurar.
- Panel `/server-status`.
- Diagnóstico público limitado `/api/system/home-server` sin hostname ni rutas locales.
- Diagnóstico administrativo `/api/admin/home-server`.
- Creación manual de respaldo y copia externa desde API.
- Instalador PowerShell para Windows y tarea programada al arrancar.
- Preparación para Cloudflare Tunnel sin apertura de puertos del módem.

## Scripts Windows

- `Instalar-Servidor-Elegance.ps1`
- `Instalar-Tunel-Cloudflare.ps1`
- `Configurar-PostgreSQL-Local.ps1`
- `Crear-Respaldo-Ahora.ps1`
- `LEEME_SERVIDOR_WINDOWS.txt`

## Seguridad

- El servidor escucha inicialmente en `127.0.0.1`.
- No abre puertos del router.
- El acceso exterior debe pasar por HTTPS mediante túnel.
- Las rutas administrativas mantienen autenticación y permisos de respaldos.
- La restauración exige confirmación y genera un respaldo preventivo.
- Las contraseñas de PostgreSQL no se imprimen durante configuración.

## Pruebas

- Producción doméstica funciona sin `DATABASE_URL`.
- Producción de nube continúa exigiendo PostgreSQL.
- Respaldo diario completo y copia externa verificados.
- Diagnóstico de almacenamiento verificado.
- Archivos del instalador Windows verificados.
- Suite total: 16 pruebas aprobadas.

## Limitaciones pendientes

- La URL permanente requiere ejecutar el instalador del túnel en la computadora real.
- Un dominio personalizado requiere disponer del dominio y asociarlo al túnel.
- PostgreSQL debe estar instalado y activo antes de ejecutar la migración real; el bloque incluye la configuración pero no puede instalarlo físicamente en una computadora no conectada a esta sesión.
- La disponibilidad pública depende de que la computadora y el internet estén encendidos.

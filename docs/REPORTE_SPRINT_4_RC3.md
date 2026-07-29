# Elegance Platform — Sprint 4 RC3

## Publicación segura y PWA

Esta versión separa el catálogo público de los módulos administrativos. En el primer inicio `/setup` exige crear el propietario; no existe contraseña fija en el código.

### Seguridad
- PBKDF2-HMAC-SHA256 con sal única y 310,000 iteraciones.
- Sesiones HttpOnly con expiración de 8 horas.
- Bloqueo de 15 minutos después de cinco intentos fallidos.
- Roles: propietario, administrador, vendedor y editor de catálogo.
- Middleware que protege rutas y endpoints privados.
- CORS configurable, encabezados de seguridad y HSTS en producción.
- Auditoría de accesos, usuarios y respaldos.

### PWA
- Manifest, icono, service worker y página offline.
- Catálogo instalable en Android y escritorio.
- Carrito persistente con `localStorage` y aviso de conexión.
- Compartir catálogo y productos.

### Respaldos
- Creación manual, listado y restauración con confirmación.
- Copia automática previa a restaurar.
- `PRAGMA integrity_check` después de restaurar.

### Ejecución
1. Ejecutar `INSTALAR_ELEGANCE.bat` cuando sea necesario.
2. Ejecutar `INICIAR_DESARROLLO.bat`.
3. Abrir `http://localhost:8000/setup` en el primer inicio.
4. Crear el propietario y entrar en `/login`.
5. El catálogo continúa público en `/catalog`.

### Producción gratuita
El paquete queda preparado para un host Python compatible con FastAPI. Configura las variables de `.env.example`, usa almacenamiento persistente para SQLite y habilita HTTPS en la plataforma. Para crecimiento posterior, migra el repositorio a PostgreSQL/Supabase sin cambiar el contrato de rutas.

# Publicar Elegance

## Opción recomendada: Render con disco persistente
1. Sube esta carpeta a un repositorio privado de GitHub.
2. En Render selecciona **New > Blueprint** y elige el repositorio.
3. Render detectará `render.yaml`. Configura `ELEGANCE_ALLOWED_ORIGINS` y `ELEGANCE_PUBLIC_URL` con la URL que Render te asigne.
4. Confirma un plan que permita disco persistente y despliega.
5. Abre la URL, entra a `/setup` y crea la contraseña propietaria.

El disco persistente es necesario para conservar SQLite, imágenes, clientes, pedidos y respaldos. Un hosting gratuito sin almacenamiento persistente puede borrar los cambios al reiniciarse.

## Ejecución local
1. Ejecuta `INSTALAR_ELEGANCE.bat` una sola vez.
2. Ejecuta `INICIAR_SPRINT5_RC1.bat`.
3. Abre `http://localhost:8000`.
4. Para administrar abre `http://localhost:8000/admin`.

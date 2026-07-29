# Elegance Platform — Sprint 5 RC2

## Objetivo
Corregir el inicio en Windows y dejar un único acceso principal que funcione desde cualquier carpeta extraída.

## Cambios
- Versión del backend: `5.2.0-rc2`.
- Nuevo centro de control en PowerShell.
- Creación automática de `.venv` dentro del paquete.
- Instalación automática de dependencias esenciales.
- Detección de Python mediante `py`, `python` o `python3`; intento opcional con Winget.
- Selección automática de puerto libre entre 8000 y 8099.
- Prevención de instancias duplicadas mediante PID persistente.
- Respaldo de SQLite antes de iniciar.
- Integridad SQLite mediante `PRAGMA integrity_check`.
- Registro de salida y errores.
- Apertura automática de portada, catálogo y administración.
- Detención y reinicio controlados.
- Eliminación de la dependencia obligatoria de Flutter para abrir la página web.
- Componentes visuales pesados separados como instalación opcional.
- Lanzadores anteriores movidos a `_ELEGANCE_SYSTEM/tools/legacy_launchers`.

## Seguridad de datos
El lanzador no modifica productos, clientes, pedidos, pagos ni inventario. Las migraciones continúan siendo responsabilidad del backend y se ejecutan después de generar un respaldo.

## Validación
- Compilación sintáctica de Python.
- Verificación de la estructura del paquete.
- Integridad de las bases SQLite.
- Arranque HTTP del backend.
- Validación de portada y catálogo públicos.
- Validación de redirección del panel administrativo sin sesión.
- Comprobación de que la raíz contiene únicamente los cuatro accesos solicitados y `_ELEGANCE_SYSTEM`.

## Limitación de validación
El archivo `.bat` y el flujo PowerShell fueron revisados estáticamente en Linux. La ejecución por doble clic requiere Windows 10/11; el backend que invocan sí fue arrancado y probado directamente.

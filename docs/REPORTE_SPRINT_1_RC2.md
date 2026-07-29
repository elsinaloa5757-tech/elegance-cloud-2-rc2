# Elegance Platform — Sprint 1 RC2

Estado: **candidato para pruebas en Windows**.

## Corrección principal

La RC1 iniciaba correctamente el backend y Flutter, pero el lanzador podía declarar un error falso porque comprobaba la interfaz únicamente mediante una petición HTTP a `127.0.0.1`.

RC2:

- inicia Flutter con `--web-hostname 0.0.0.0`;
- detecta la disponibilidad mediante el puerto TCP 54105;
- tolera diferencias entre `localhost`, IPv4, IPv6 y proxy de Windows;
- espera hasta cinco minutos mostrando progreso;
- abre `http://localhost:54105` al confirmar que el puerto está escuchando;
- mantiene el backend y la base de datos de RC1 sin alteraciones funcionales.

## Validaciones realizadas en el entorno de empaquetado

- estructura del paquete;
- presencia de backend y Flutter;
- compilación sintáctica de Python;
- integridad SQLite;
- ausencia de rutas absolutas activas en los lanzadores nuevos;
- empaquetado e integridad ZIP.

La ejecución final de PowerShell, Flutter y navegador debe validarse en Windows.

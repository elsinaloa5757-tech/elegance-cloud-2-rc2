# Elegance Platform — Sprint 1 RC1

## Estado
**Candidato listo para prueba en Windows. Sprint todavía no aprobado.**

## Base utilizada
`elegance_v26_controlada_sobre_v25(2).zip`

## Alcance aplicado
- Limpieza de la raíz: solo instalación, inicio y carpeta interna.
- Código funcional original conservado en `_ELEGANCE_SYSTEM/app`.
- Historial movido a `_ELEGANCE_SYSTEM/docs/historial`.
- Scripts anteriores conservados como referencia en `_ELEGANCE_SYSTEM/scripts`.
- Instalación transaccional en `%LOCALAPPDATA%\ElegancePlatform`.
- Respaldo previo antes de reemplazar una instalación existente.
- Preservación de la base SQLite más reciente encontrada.
- Inicio con rutas calculadas dinámicamente.

## Verificaciones realizadas en el entorno de construcción
- Estructura y archivos obligatorios: aprobados.
- Sintaxis Python mediante `compileall`: aprobada.
- Integridad SQLite (`PRAGMA integrity_check`): aprobada.
- Búsqueda de rutas absolutas en scripts activos: aprobada; solo existen rutas heredadas dentro de la lista de recuperación de bases.
- Contenido original de backend y Flutter: conservado.
- Integridad del ZIP: aprobada.

## Verificación pendiente en Windows
El entorno de construcción no dispone de Flutter ni PowerShell de Windows. Por tanto, la ejecución real de `flutter pub get`, `flutter analyze`, instalación e inicio debe confirmarse en la computadora del usuario. Los scripts ejecutan estas comprobaciones antes de reemplazar la instalación activa.

## Criterio de aprobación
El Sprint 1 solo queda aprobado cuando:
1. `INSTALAR_ELEGANCE.bat` termina sin error.
2. `INICIAR_ELEGANCE.bat` abre el panel.
3. El catálogo y la base existente permanecen disponibles.

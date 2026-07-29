# Elegance Cloud 2 RC2 — Bloque 9

## Alcance

Instalación definitiva y administración segura para servidor Windows doméstico.

## Implementado

- Actualizador no destructivo que conserva `C:\EleganceServer\data` y `.env.server`.
- Resguardo del código anterior en `C:\EleganceServer\updates`.
- Arranque automático al iniciar Windows y al iniciar sesión.
- Ejecución oculta en segundo plano con la orden verificada de Uvicorn.
- Reinicio configurado en el Programador de tareas.
- Vigilante de salud cada cinco minutos.
- Registros separados de servidor y vigilante.
- Diagnóstico de instalación.
- Validación automática de `/api/health`, `/admin`, `/mobile-center` y `/server-status`.
- Escucha local en `127.0.0.1`; no se abren puertos del módem.

## Tareas registradas

- `Elegance Server`
- `Elegance Server Watchdog`

## Validación

25 pruebas automáticas aprobadas.

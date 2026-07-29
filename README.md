# Elegance Platform Cloud 2.0 RC2

Plataforma integral de catálogo, inventario, ventas, apartados, pagos, envíos,
automatización móvil y operación pública de Elegance.

## Inicio rápido

Requiere Python 3.11 o 3.12.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8000
```

En Windows, activa el entorno con `.venv\Scripts\activate`.

La aplicación queda disponible en `http://localhost:8000` y el estado del
sistema en `http://localhost:8000/api/system/status`.

## Producción

El repositorio incluye `Dockerfile` y `render.yaml`. En producción configura:

- `ELEGANCE_ENV=production`
- `ELEGANCE_DATA_DIR=/data`
- `ELEGANCE_ALLOWED_ORIGINS`
- `ELEGANCE_PUBLIC_URL`
- `DATABASE_URL`
- Credenciales de Supabase cuando se utilice sincronización y almacenamiento

`/data` debe ser un volumen persistente. Las bases, respaldos, productos y
archivos comerciales no se almacenan en GitHub.

## Validación

```bash
pip install -r requirements-dev.txt
pytest -q
```

Consulta `docs/` para el historial técnico y los reportes de cada bloque.

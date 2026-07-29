ELEGANCE AI v2.0 — PARCHE DE CLASIFICACIÓN
==========================================

QUÉ AÑADE
---------
- Marca provisional.
- Familia de modelo provisional.
- Tipo de calzado.
- Material aparente.
- Color dominante.
- Puntuación de calidad.
- Título sugerido.
- Bandera de revisión manual.
- Top 3 de marca y modelo.
- Compatibilidad con /group y Flutter actual.

IMPORTANTE
----------
La clasificación es zero-shot con CLIP.
No garantiza SKU, colorway comercial ni autenticidad.

INSTALACIÓN
-----------
1. Detén el servidor con CTRL+C.

2. Haz copia de seguridad de:
   C:\src\elegance_ai_v1\models\clip_engine.py
   C:\src\elegance_ai_v1\models\schemas.py
   C:\src\elegance_ai_v1\services\analyzer.py
   C:\src\elegance_ai_v1\services\quality.py

3. Extrae este ZIP.

4. Copia las carpetas models y services dentro de:
   C:\src\elegance_ai_v1

5. Acepta reemplazar archivos y agregar:
   services\classifier.py

6. Inicia:
   cd C:\src\elegance_ai_v1
   start_server.bat

7. Abre:
   http://127.0.0.1:8000/health

Debe mostrar:
   "version":"2.0.0"

8. Abre Flutter y vuelve a analizar tus imágenes.

NOTA DE FLUTTER
---------------
Tu Flutter actual seguirá mostrando los grupos.
Los nuevos campos de marca, modelo y título ya vendrán en el JSON,
pero todavía no se verán en pantalla hasta instalar el parche visual
de Flutter v2.

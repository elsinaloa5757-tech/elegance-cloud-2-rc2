elegance V10 — flujo automático verificado

FLUJO OBLIGATORIO
1. Recibe todas las fotografías.
2. Advierte duplicados casi exactos; conserva vistas diferentes.
3. Agrupa las vistas del mismo producto.
4. Recorta la imagen para verificación visual.
5. Google Vision Web Detection busca coincidencias en la web.
6. Solo confirma el nombre si encuentra al menos 3 fuentes independientes
   que coinciden con el mismo modelo conocido.
7. Genera el escenario final de elegance.
8. Solo los productos confirmados y con escenario final pasan al catálogo.
9. Catálogo y Publicaciones usan la imagen final, nunca la original.

IMPORTANTE SOBRE LA BÚSQUEDA WEB
La búsqueda automática necesita una Google Vision API key. Configúrala en:
Configuración > Verificación visual en la web.
Sin clave, V10 genera el escenario pero no inventa ni publica un nombre.

DIAGNÓSTICO
- http://127.0.0.1:8000/health
- http://127.0.0.1:8000/routes
Ambas direcciones deben responder antes de usar Auto Sync o Studio.

INSTALACIÓN
1. Cierra las ventanas anteriores de Flutter y Python.
2. Ejecuta INSTALAR_ELEGANCE_V10.bat.
3. Ejecuta INICIAR_ELEGANCE_V10.bat.
4. Abre http://localhost:54105 si Edge no abre automáticamente.

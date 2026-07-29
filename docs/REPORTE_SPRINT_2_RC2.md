# Elegance Platform — Sprint 2 RC2

## Objetivo cumplido
Integración de categorías universales en interfaz, navegación y catálogo, con clasificación automática conservadora y preservación completa de productos existentes.

## Cambios principales
- 7 categorías raíz y 43 subcategorías disponibles en el catálogo.
- Filtros de Categoría, Subcategoría y Marca en la interfaz.
- Búsqueda ampliada por título, SKU, marca, categoría y subcategoría.
- Clasificador automático local basado en señales de nombre, marca, modelo, notas y SKU.
- Valores existentes de categoría se respetan cuando son válidos.
- Productos heredados de sneakers/calzado migran de forma segura a Calzado > Sneakers cuando no existe evidencia contraria.
- Cada producto conserva ID, imágenes, galería, precio, stock, tallas, notas y fecha.
- Nueva ruta física opcional: Categoría/Subcategoría/Marca/Modelo.
- Estado comercial mantiene compatibilidad hacia atrás y añade categorySchemaVersion=2.

## Endpoint de migración
POST /api/catalog/reorganize

Devuelve conteos de clasificados, preservados, normalizados, archivos movidos, categorías y subcategorías.

## Seguridad de datos
La migración es aditiva: no elimina productos ni reinicializa la base comercial. Los campos nuevos tienen valores compatibles para productos antiguos.

## Versión
26.2.0-sprint2-rc2

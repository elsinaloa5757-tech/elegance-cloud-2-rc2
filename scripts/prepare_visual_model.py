"""Warm up rembg and download its segmentation model during installation."""
from io import BytesIO
from PIL import Image

try:
    from rembg import remove
except Exception as exc:
    print(f"AVISO: motor neuronal no disponible: {exc}")
    raise SystemExit(0)

image = Image.new("RGB", (32, 32), "white")
buffer = BytesIO()
image.save(buffer, format="PNG")
try:
    remove(buffer.getvalue())
    print("Motor visual neuronal preparado.")
except Exception as exc:
    print(f"AVISO: no se pudo preparar el modelo neuronal; se usará el respaldo local: {exc}")

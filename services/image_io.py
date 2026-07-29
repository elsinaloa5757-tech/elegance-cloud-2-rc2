from __future__ import annotations

import io
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class DecodedImage:
    pil: Image.Image
    bgr: np.ndarray
    width: int
    height: int


def decode_image(data: bytes) -> DecodedImage:
    try:
        pil = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as exc:
        raise ValueError("No se pudo abrir una de las imágenes.") from exc

    rgb = np.asarray(pil)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    return DecodedImage(
        pil=pil,
        bgr=bgr,
        width=pil.width,
        height=pil.height,
    )

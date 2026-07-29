from __future__ import annotations

import cv2
import numpy as np


COLOR_REFERENCES: dict[str, tuple[int, int, int]] = {
    "Negro": (25, 25, 25),
    "Blanco": (235, 235, 235),
    "Gris": (135, 135, 135),
    "Rojo": (205, 45, 45),
    "Azul": (55, 95, 205),
    "Verde": (65, 155, 85),
    "Amarillo": (230, 195, 45),
    "Naranja": (225, 125, 40),
    "Rosa": (220, 125, 165),
    "Morado": (130, 80, 165),
    "Café": (125, 85, 55),
    "Beige": (205, 185, 145),
}


def dominant_color(
    image_bgr: np.ndarray,
) -> tuple[str, list[int]]:
    height, width = image_bgr.shape[:2]

    x1 = int(width * 0.15)
    x2 = int(width * 0.85)
    y1 = int(height * 0.15)
    y2 = int(height * 0.85)

    crop = image_bgr[y1:y2, x1:x2]
    resized = cv2.resize(
        crop,
        (96, 96),
        interpolation=cv2.INTER_AREA,
    )

    pixels = cv2.cvtColor(
        resized,
        cv2.COLOR_BGR2RGB,
    ).reshape(-1, 3)

    # Ignora extremos muy blancos y muy negros del fondo.
    brightness = pixels.mean(axis=1)
    useful = pixels[
        (brightness > 25) & (brightness < 240)
    ]

    if len(useful) < 64:
        useful = pixels

    mean_rgb = useful.mean(axis=0)
    rgb = [int(round(value)) for value in mean_rgb]

    best_name = "Desconocido"
    best_distance = float("inf")

    for name, reference in COLOR_REFERENCES.items():
        distance = float(
            np.linalg.norm(
                mean_rgb - np.asarray(reference),
            )
        )

        if distance < best_distance:
            best_distance = distance
            best_name = name

    return best_name, rgb

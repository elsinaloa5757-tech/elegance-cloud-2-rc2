from __future__ import annotations

import cv2
import numpy as np


def sharpness_score(
    image_bgr: np.ndarray,
) -> float:
    gray = cv2.cvtColor(
        image_bgr,
        cv2.COLOR_BGR2GRAY,
    )

    score = cv2.Laplacian(
        gray,
        cv2.CV_64F,
    ).var()

    return round(float(score), 2)


def quality_score(
    image_bgr: np.ndarray,
) -> tuple[float, str]:
    gray = cv2.cvtColor(
        image_bgr,
        cv2.COLOR_BGR2GRAY,
    )

    sharpness = cv2.Laplacian(
        gray,
        cv2.CV_64F,
    ).var()

    brightness = float(gray.mean())
    contrast = float(gray.std())

    sharp_component = min(
        1.0,
        sharpness / 500.0,
    )

    brightness_component = max(
        0.0,
        1.0 - abs(brightness - 135.0) / 135.0,
    )

    contrast_component = min(
        1.0,
        contrast / 70.0,
    )

    score = (
        sharp_component * 0.55
        + brightness_component * 0.20
        + contrast_component * 0.25
    ) * 10.0

    score = round(
        max(0.0, min(10.0, score)),
        2,
    )

    if score >= 8.0:
        label = "Excelente"
    elif score >= 6.5:
        label = "Buena"
    elif score >= 5.0:
        label = "Aceptable"
    else:
        label = "Revisar"

    return score, label

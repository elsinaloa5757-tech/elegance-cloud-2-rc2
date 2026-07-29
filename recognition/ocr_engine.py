from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

SKU_PATTERNS = [
    re.compile(r"\b[A-Z]{1,3}\d{3,6}-\d{2,4}\b", re.I),   # DD1391-100, FQ8138-001
    re.compile(r"\b\d{5,8}-\d{2,4}\b"),                  # 604133-050
    re.compile(r"\b[A-Z]{2,5}\d{3,8}\b", re.I),          # EG4958, U9060GRY
    re.compile(r"\b\d{8,12}\b"),                         # códigos largos de estilo
]

@dataclass(frozen=True)
class OcrResult:
    text: str
    sku_candidates: list[str]
    engine: str


def _extract_skus(text: str) -> list[str]:
    found: list[str] = []
    for pattern in SKU_PATTERNS:
        for value in pattern.findall(text.upper()):
            normalized = re.sub(r"\s+", "", value)
            if normalized not in found:
                found.append(normalized)
    return found[:10]


def _filename_text(filenames: list[str]) -> str:
    parts = []
    for filename in filenames:
        stem = Path(filename).stem
        parts.append(re.sub(r"[_+.]+", " ", stem))
    return " ".join(parts)


def read_text(images_bgr: list[np.ndarray], filenames: list[str]) -> OcrResult:
    """OCR local opcional. Siempre examina nombres de archivo; usa Tesseract si existe."""
    collected = [_filename_text(filenames)]
    engine = "filename"
    try:
        import pytesseract  # type: ignore
        # En Windows pytesseract detecta tesseract.exe si está en PATH.
        for image in images_bgr[:4]:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC)
            gray = cv2.bilateralFilter(gray, 7, 35, 35)
            text = pytesseract.image_to_string(gray, config="--psm 11")
            if text.strip():
                collected.append(text)
        engine = "tesseract+filename"
    except Exception:
        pass
    text = "\n".join(x for x in collected if x.strip())
    return OcrResult(text=text, sku_candidates=_extract_skus(text), engine=engine)

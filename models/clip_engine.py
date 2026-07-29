from __future__ import annotations

from threading import Lock
from typing import Iterable

import numpy as np
try:
    import torch
except ImportError:
    torch = None  # type: ignore
from PIL import Image, ImageOps
try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # El catálogo y la administración funcionan sin el modelo visual opcional.
    SentenceTransformer = None  # type: ignore


class ClipEngine:
    MODEL_NAME = "clip-ViT-B-32"

    def __init__(self) -> None:
        self._model = None
        self._lock = Lock()
        self._text_cache: dict[tuple[str, ...], np.ndarray] = {}

    @property
    def device(self) -> str:
        return "cuda" if torch is not None and torch.cuda.is_available() else "cpu"

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self):
        if self._model is not None:
            return self._model
        if SentenceTransformer is None:
            raise RuntimeError('El modelo visual opcional no está instalado. Instala sentence-transformers para usar reconocimiento CLIP.')

        with self._lock:
            if self._model is None:
                self._model = SentenceTransformer(
                    self.MODEL_NAME,
                    device=self.device,
                )

        return self._model

    @staticmethod
    def _center_crop(
        image: Image.Image,
        ratio: float = 0.82,
    ) -> Image.Image:
        width, height = image.size
        crop_width = max(1, int(width * ratio))
        crop_height = max(1, int(height * ratio))

        left = max(0, (width - crop_width) // 2)
        top = max(0, (height - crop_height) // 2)

        return image.crop(
            (
                left,
                top,
                left + crop_width,
                top + crop_height,
            )
        )

    def encode_multiview(
        self,
        images: list[Image.Image],
    ) -> np.ndarray:
        if not images:
            raise ValueError("No hay imágenes para codificar.")

        augmented: list[Image.Image] = []

        for image in images:
            rgb = image.convert("RGB")
            crop = self._center_crop(rgb)

            augmented.extend(
                [
                    rgb,
                    crop,
                    ImageOps.mirror(crop),
                ]
            )

        encoded = self.load().encode(
            augmented,
            batch_size=12,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )

        encoded = np.asarray(
            encoded,
            dtype=np.float32,
        ).reshape(len(images), 3, -1)

        averaged = encoded.mean(axis=1)
        averaged /= np.clip(
            np.linalg.norm(
                averaged,
                axis=1,
                keepdims=True,
            ),
            1e-12,
            None,
        )

        return averaged.astype(np.float32)

    def encode_texts(
        self,
        prompts: Iterable[str],
    ) -> np.ndarray:
        key = tuple(prompts)

        cached = self._text_cache.get(key)

        if cached is not None:
            return cached

        embeddings = self.load().encode(
            list(key),
            batch_size=32,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )

        result = np.asarray(
            embeddings,
            dtype=np.float32,
        )

        self._text_cache[key] = result
        return result

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass

import numpy as np
from fastapi import UploadFile

from models.clip_engine import ClipEngine
from models.schemas import (
    AnalyzeResponse,
    GroupItem,
    ImageMetadata,
    Prediction,
    ProductGroup,
)
from recognition.recognizer import recognize_group
from services.color import dominant_color
from services.duplicate import sha256_bytes
from services.grouping import (
    cluster_embeddings,
    group_confidences,
    representative_index,
    visual_duplicate_pairs,
)
from services.image_io import decode_image
from services.quality import (
    quality_score,
    sharpness_score,
)


@dataclass
class LoadedUpload:
    filename: str
    data: bytes


@dataclass
class WorkingImage:
    original_index: int
    filename: str
    data: bytes
    decoded: object
    color_name: str
    color_rgb: list[int]
    sharpness: float
    quality_score: float
    quality_label: str
    duplicate: bool
    duplicate_of: int | None


class AnalyzerService:
    VERSION = "23.1.0"

    def __init__(self) -> None:
        self.engine = ClipEngine()

    def health(self) -> dict[str, object]:
        return {
            "status": "ok",
            "service": "Elegance AI",
            "version": self.VERSION,
            "model": self.engine.MODEL_NAME,
            "model_loaded": self.engine.loaded,
            "device": self.engine.device,
        }

    async def analyze(
        self,
        uploads: list[UploadFile],
        *,
        eps: float,
        min_samples: int,
    ) -> AnalyzeResponse:
        # Leer la red de forma asíncrona y ejecutar OpenCV/CLIP/OCR fuera del
        # event loop. Así /health y la interfaz siguen respondiendo durante lotes.
        loaded: list[LoadedUpload] = []
        for index, upload in enumerate(uploads):
            data = await upload.read()
            if not data:
                raise ValueError(f"{upload.filename or f'imagen_{index + 1}'} está vacío.")
            loaded.append(LoadedUpload(filename=upload.filename or f"imagen_{index + 1}", data=data))
        return await asyncio.to_thread(self._analyze_loaded, loaded, eps, min_samples)

    def _analyze_loaded(
        self,
        uploads: list[LoadedUpload],
        eps: float,
        min_samples: int,
    ) -> AnalyzeResponse:
        del min_samples

        working: list[WorkingImage] = []
        exact_unique: list[WorkingImage] = []
        seen_hashes: dict[str, int] = {}

        for index, upload in enumerate(uploads):
            data = upload.data
            decoded = decode_image(data)
            digest = sha256_bytes(data)

            duplicate_of = seen_hashes.get(digest)
            duplicate = duplicate_of is not None

            if not duplicate:
                seen_hashes[digest] = index

            color_name, color_rgb = dominant_color(
                decoded.bgr
            )

            quality_value, quality_label = quality_score(
                decoded.bgr
            )

            item = WorkingImage(
                original_index=index,
                filename=upload.filename
                or f"imagen_{index + 1}",
                data=data,
                decoded=decoded,
                color_name=color_name,
                color_rgb=color_rgb,
                sharpness=sharpness_score(
                    decoded.bgr
                ),
                quality_score=quality_value,
                quality_label=quality_label,
                duplicate=duplicate,
                duplicate_of=duplicate_of,
            )

            working.append(item)

            if not duplicate:
                exact_unique.append(item)

        if not exact_unique:
            raise ValueError(
                "No quedaron imágenes únicas para analizar."
            )

        embeddings = self.engine.encode_multiview(
            [
                item.decoded.pil
                for item in exact_unique
            ]
        )

        # Solo se eliminan duplicados byte-a-byte (SHA-256).
        # Fotografías diferentes o ángulos distintos siempre se conservan.
        visual_duplicates: dict[int, int] = {}

        analysis_items: list[WorkingImage] = []
        analysis_embeddings: list[np.ndarray] = []

        for local_index, item in enumerate(exact_unique):
            if local_index in visual_duplicates:
                original_item = exact_unique[
                    visual_duplicates[local_index]
                ]

                item.duplicate = True
                item.duplicate_of = (
                    original_item.original_index
                )
                continue

            analysis_items.append(item)
            analysis_embeddings.append(
                embeddings[local_index]
            )

        final_embeddings = np.vstack(
            analysis_embeddings
        ).astype(np.float32)

        distance_threshold = max(
            0.045,
            min(0.14, float(eps)),
        )

        grouped_positions = cluster_embeddings(
            final_embeddings,
            [
                item.color_rgb
                for item in analysis_items
            ],
            distance_threshold=distance_threshold,
            color_threshold=60.0,
        )

        sharpness_values = [
            item.sharpness
            for item in analysis_items
        ]

        groups: list[ProductGroup] = []

        for group_number, positions in enumerate(
            grouped_positions,
            start=1,
        ):
            confidences = group_confidences(
                final_embeddings,
                positions,
            )

            cover_position = representative_index(
                final_embeddings,
                positions,
                sharpness_values,
            )

            cover_original_index = analysis_items[
                cover_position
            ].original_index

            candidates = [
                analysis_items[position]
                for position in positions
            ]

            dominant = Counter(
                candidate.color_name
                for candidate in candidates
            ).most_common(1)[0][0]

            group_embedding = final_embeddings[
                positions
            ].mean(axis=0)

            group_embedding /= np.clip(
                np.linalg.norm(group_embedding),
                1e-12,
                None,
            )

            recognition = recognize_group(
                engine=self.engine,
                embeddings=final_embeddings[positions],
                images_bgr=[candidate.decoded.bgr for candidate in candidates],
                filenames=[candidate.filename for candidate in candidates],
                dominant_color=dominant,
            )

            resolved_brand = recognition.brand
            manual_review = recognition.needs_review
            suggested_title = recognition.title

            group_items: list[GroupItem] = []

            for local_position, position in enumerate(
                positions
            ):
                candidate = analysis_items[position]

                group_items.append(
                    GroupItem(
                        index=candidate.original_index,
                        filename=candidate.filename,
                        confidence=confidences[
                            local_position
                        ],
                        is_cover=(
                            candidate.original_index
                            == cover_original_index
                        ),
                    )
                )

            groups.append(
                ProductGroup(
                    group_id=group_number,
                    count=len(group_items),
                    cover_index=cover_original_index,
                    average_confidence=round(
                        sum(confidences)
                        / len(confidences),
                        4,
                    ),
                    dominant_color=dominant,

                    brand=resolved_brand,
                    brand_confidence=recognition.brand_confidence,

                    model_family=recognition.model,
                    model_confidence=recognition.model_confidence,

                    shoe_type="footwear",
                    type_confidence=0.0,

                    material="mixed materials",
                    material_confidence=0.0,

                    suggested_title=suggested_title,
                    needs_manual_review=manual_review,
                    sku=recognition.sku,
                    identification_method=recognition.method,
                    identification_evidence=recognition.evidence,
                    ocr_engine=recognition.ocr_engine,

                    brand_predictions=[
                        Prediction(label=item.label, confidence=item.confidence)
                        for item in recognition.brand_predictions
                    ],
                    model_predictions=[
                        Prediction(label=item.label, confidence=item.confidence)
                        for item in recognition.model_predictions
                    ],

                    items=group_items,
                )
            )

        metadata = [
            ImageMetadata(
                index=item.original_index,
                filename=item.filename,
                duplicate=item.duplicate,
                duplicate_of=item.duplicate_of,
                dominant_color=item.color_name,
                dominant_rgb=item.color_rgb,
                sharpness=item.sharpness,
                quality_score=item.quality_score,
                quality_label=item.quality_label,
                width=item.decoded.width,
                height=item.decoded.height,
            )
            for item in working
        ]

        duplicate_count = sum(
            1
            for item in working
            if item.duplicate
        )

        return AnalyzeResponse(
            status="ok",
            engine=(
"CLIP brand-first + consenso multivista + OCR local + aprendizaje"
            ),
            model=self.engine.MODEL_NAME,
            device=self.engine.device,
            images_received=len(working),
            unique_images=(
                len(working) - duplicate_count
            ),
            duplicate_images=duplicate_count,
            groups_found=len(groups),
            parameters={
                "eps": distance_threshold,
                "min_samples": 1,
            },
            groups=groups,
            images=metadata,
            warning=(
                "Elegance V22 usa marca primero, consenso entre vistas, OCR local opcional y una base aprendida. Los casos débiles quedan marcados para revisión sin bloquear el catálogo."
            ),
        )

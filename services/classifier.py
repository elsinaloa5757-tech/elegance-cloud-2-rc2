from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from models.clip_engine import ClipEngine


@dataclass(frozen=True)
class LabelPrediction:
    label: str
    confidence: float


BRANDS = [
    "Nike",
    "Jordan",
    "Adidas",
    "New Balance",
    "Puma",
    "Asics",
    "Converse",
    "Vans",
    "Reebok",
    "Balenciaga",
    "On",
    "Hoka",
    "Under Armour",
    "Saucony",
    "Fila",
    "Louis Vuitton",
    "Gucci",
    "Dior",
    "Hugo Boss",
    "Amiri",
    "Timberland",
    "Dr. Martens",
    "Unknown",
]

MODEL_FAMILIES = [
    "Jordan 1 Low",
    "Jordan 1 Mid",
    "Jordan 1 High",
    "Jordan 3",
    "Jordan 4",
    "Jordan 5",
    "Jordan 11",
    "Nike Dunk Low",
    "Nike Dunk High",
    "Nike Air Force 1",
    "Nike Air Max",
    "Nike Air Max 270",
    "Nike Air Max 720",
    "Nike Air Max Dn",
    "Nike Air Max Plus TN",
    "Nike Blazer",
    "Nike Cortez",
    "Adidas Samba",
    "Adidas Campus",
    "Adidas Gazelle",
    "Adidas Forum",
    "Adidas Yeezy",
    "Adidas Superstar",
    "Adidas NMD",
    "Adidas Ultraboost",
    "New Balance 530",
    "New Balance 550",
    "New Balance 9060",
    "New Balance 1906R",
    "New Balance 2002R",
    "New Balance 990",
    "New Balance 327",
    "Asics Gel",
    "On Cloud",
    "Hoka running shoe",
    "Balenciaga Speed",
    "Balenciaga Track",
    "Converse Chuck Taylor",
    "Vans Old Skool",
    "Nike Shox",
    "Nike Vapormax",
    "Nike Air Max 90",
    "Nike Air Max 95",
    "Nike Air Max 97",
    "Adidas Yeezy 350",
    "Adidas Yeezy 500",
    "Adidas Yeezy 700",
    "Puma Speedcat",
    "Puma RS-X",
    "Louis Vuitton Trainer",
    "Gucci Rhyton",
    "Dior B23",
    "Dior B30",
    "Hugo Boss sneaker",
    "Balenciaga Triple S",
    "Balenciaga 3XL",
    "Timberland 6 inch boot",
    "Dr. Martens boot",
    "Other sneaker",
    "Other boot",
]

SHOE_TYPES = [
    "low top sneaker",
    "mid top sneaker",
    "high top sneaker",
    "running shoe",
    "basketball shoe",
    "skate shoe",
    "sock sneaker",
    "casual lifestyle sneaker",
    "trail shoe",
    "ankle boot",
    "work boot",
    "fashion boot",
    "chelsea boot",
    "combat boot",
]

MATERIALS = [
    "smooth leather",
    "suede",
    "nubuck",
    "mesh",
    "knit fabric",
    "canvas",
    "synthetic leather",
    "patent leather",
    "mixed materials",
]


def _prompts(
    labels: list[str],
    template: str,
) -> list[str]:
    return [
        template.format(label=label)
        for label in labels
    ]


def _softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - values.max()
    exp = np.exp(shifted)
    return exp / np.clip(exp.sum(), 1e-12, None)


def classify(
    engine: ClipEngine,
    image_embedding: np.ndarray,
    labels: list[str],
    template: str,
    top_k: int = 3,
) -> list[LabelPrediction]:
    text_embeddings = engine.encode_texts(
        _prompts(labels, template)
    )

    similarities = cosine_similarity(
        image_embedding.reshape(1, -1),
        text_embeddings,
    ).reshape(-1)

    probabilities = _softmax(
        similarities * 18.0
    )

    order = np.argsort(probabilities)[::-1][:top_k]

    return [
        LabelPrediction(
            label=labels[index],
            confidence=round(
                float(probabilities[index]),
                4,
            ),
        )
        for index in order
    ]


def classify_group(
    engine: ClipEngine,
    group_embedding: np.ndarray,
) -> dict[str, list[LabelPrediction]]:
    return {
        "brand": classify(
            engine,
            group_embedding,
            BRANDS,
            "a close catalog product photograph clearly showing the logo and shape of a {label} shoe",
        ),
        "model": classify(
            engine,
            group_embedding,
            MODEL_FAMILIES,
            "a close catalog photograph of the exact footwear model {label}, isolated from the background",
        ),
        "type": classify(
            engine,
            group_embedding,
            SHOE_TYPES,
            "a product photo of a {label}",
        ),
        "material": classify(
            engine,
            group_embedding,
            MATERIALS,
            "a close product photo of a sneaker made of {label}",
        ),
    }

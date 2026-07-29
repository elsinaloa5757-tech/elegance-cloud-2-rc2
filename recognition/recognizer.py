from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from models.clip_engine import ClipEngine
from recognition.catalog import BRANDS, MODELS_BY_BRAND
from recognition.learning_store import best_match
from recognition.ocr_engine import OcrResult, read_text
from recognition.title_builder import build_title

@dataclass(frozen=True)
class Candidate:
    label: str
    confidence: float

@dataclass(frozen=True)
class RecognitionResult:
    brand: str
    brand_confidence: float
    model: str
    model_confidence: float
    title: str
    sku: str
    needs_review: bool
    method: str
    evidence: list[str]
    brand_predictions: list[Candidate]
    model_predictions: list[Candidate]
    ocr_engine: str


def _softmax(values: np.ndarray, temperature: float = 20.0) -> np.ndarray:
    x = values * temperature
    x = x - x.max(axis=-1, keepdims=True)
    e = np.exp(x)
    return e / np.clip(e.sum(axis=-1, keepdims=True), 1e-12, None)


def _brand_from_text(text: str) -> str:
    value = " " + " ".join(text.lower().replace("_", " ").split()) + " "
    aliases = [
        (("air jordan", "jumpman", " jordan "), "Jordan"),
        (("new balance", " newbalance ", " nb "), "New Balance"),
        (("adidas", "yeezy"), "Adidas"),
        (("hugo boss", " boss ", " hugo "), "Hugo Boss"),
        (("louis vuitton", " louisvuitton ", " lv "), "Louis Vuitton"),
        (("dr martens", "doc martens", "martens"), "Dr. Martens"),
        (("under armour", "underarmor"), "Under Armour"),
        (("converse", "chuck taylor"), "Converse"),
        (("balenciaga",), "Balenciaga"),
        (("timberland",), "Timberland"),
        (("saucony",), "Saucony"),
        (("reebok",), "Reebok"),
        (("asics",), "Asics"),
        (("puma",), "Puma"),
        (("vans",), "Vans"),
        (("gucci",), "Gucci"),
        (("dior",), "Dior"),
        (("amiri",), "Amiri"),
        (("hoka",), "Hoka"),
        ((" nike ", "swoosh"), "Nike"),
        ((" fila ",), "Fila"),
    ]
    for tokens, brand in aliases:
        if any(token in value for token in tokens):
            return brand
    return ""


def _classify_views(engine: ClipEngine, embeddings: np.ndarray, labels: list[str], template: str, top_k: int = 4) -> list[Candidate]:
    prompts = [template.format(label=x) for x in labels]
    text_embeddings = engine.encode_texts(prompts)
    similarities = cosine_similarity(embeddings, text_embeddings)
    probabilities = _softmax(similarities)
    # El consenso usa la media, pero premia ligeramente la mejor vista.
    aggregate = probabilities.mean(axis=0) * 0.8 + probabilities.max(axis=0) * 0.2
    order = np.argsort(aggregate)[::-1][:top_k]
    return [Candidate(labels[i], round(float(aggregate[i]), 4)) for i in order]


def recognize_group(
    *,
    engine: ClipEngine,
    embeddings: np.ndarray,
    images_bgr: list[np.ndarray],
    filenames: list[str],
    dominant_color: str,
) -> RecognitionResult:
    brand_predictions = _classify_views(
        engine, embeddings, BRANDS,
        "a clear product photograph of a {label} footwear item, showing its authentic logo, sole and silhouette",
    )
    brand = brand_predictions[0]
    brand_margin = brand.confidence - (brand_predictions[1].confidence if len(brand_predictions) > 1 else 0.0)

    selected_brand = brand.label
    model_labels = MODELS_BY_BRAND.get(selected_brand, [])
    if not model_labels:
        model_labels = ["sneaker", "running shoe", "high-top sneaker", "boot"]

    model_predictions = _classify_views(
        engine, embeddings, model_labels,
        f"an authentic {selected_brand} {{label}} product photograph, exact model silhouette, sole and upper panels",
    )
    model = model_predictions[0]
    model_margin = model.confidence - (model_predictions[1].confidence if len(model_predictions) > 1 else 0.0)

    group_embedding = embeddings.mean(axis=0)
    group_embedding /= np.clip(np.linalg.norm(group_embedding), 1e-12, None)
    learned = best_match(group_embedding, brand=selected_brand)
    ocr: OcrResult = read_text(images_bgr, filenames)
    sku = ocr.sku_candidates[0] if ocr.sku_candidates else ""
    text_brand = _brand_from_text(ocr.text)
    if text_brand:
        selected_brand = text_brand
        model_labels = MODELS_BY_BRAND.get(selected_brand, []) or ["sneaker", "running shoe", "high-top sneaker", "boot"]
        model_predictions = _classify_views(
            engine, embeddings, model_labels,
            f"an authentic {selected_brand} {{label}} product photograph, exact model silhouette, sole and upper panels",
        )
        model = model_predictions[0]
        model_margin = model.confidence - (model_predictions[1].confidence if len(model_predictions) > 1 else 0.0)

    evidence = [
        f"Marca por consenso de {len(embeddings)} vista(s): {selected_brand} {brand.confidence:.0%}",
        f"Modelo dentro de {selected_brand}: {model.label} {model.confidence:.0%}",
        f"Margen de marca: {brand_margin:.0%}; margen de modelo: {model_margin:.0%}",
    ]
    method_parts = ["clip-brand-first", "multi-view"]
    if text_brand:
        evidence.append(f"Marca confirmada por texto/OCR local: {text_brand}")
        method_parts.append("ocr-brand")

    final_brand = selected_brand
    final_model = model.label
    final_title = build_title(brand=final_brand, model=final_model, color=dominant_color, sku=sku)
    learned_similarity = 0.0
    if learned is not None:
        learned_similarity = learned.similarity
        evidence.append(f"Base aprendida: {learned.title} ({learned.similarity:.1%})")
        if learned.similarity >= 0.91:
            final_brand = learned.brand
            final_model = learned.model
            final_title = learned.title
            sku = sku or learned.sku
            method_parts.append("learned-reference")

    if sku:
        evidence.append(f"SKU/código leído localmente: {sku}")
        method_parts.append("ocr")

    # Regla V23: primero la marca; el modelo solo se guarda con evidencia fuerte.
    # Nunca se inventa un modelo para desbloquear el catálogo.
    # Las probabilidades se reparten entre muchas marcas. Con 24 etiquetas,
    # 8-15% ya puede ser una señal fuerte; por eso se usa evidencia relativa
    # (margen y múltiplo sobre la probabilidad uniforme), no un 34% imposible.
    uniform_brand = 1.0 / max(len(BRANDS), 1)
    uniform_model = 1.0 / max(len(model_labels), 1)
    brand_is_reliable = (
        final_brand not in {"", "Unknown", "Sin identificar"}
        and (
            bool(text_brand)
            or learned_similarity >= 0.91
            or bool(sku)
            or (brand.confidence >= max(0.072, uniform_brand * 1.65) and brand_margin >= 0.006)
        )
    )
    model_is_reliable = (
        brand_is_reliable
        and final_model not in {"", "Other sneaker", "sneaker", "running shoe", "high-top sneaker", "boot"}
        and (
            learned_similarity >= 0.91
            or bool(sku)
            or (model.confidence >= max(0.105, uniform_model * 1.35) and model_margin >= 0.006)
        )
    )

    if not brand_is_reliable:
        final_brand = "Sin identificar"
        final_model = ""
        evidence.append("Marca insuficiente: se dejó pendiente para evitar una asignación falsa.")
    elif not model_is_reliable:
        final_model = ""
        evidence.append("Modelo insuficiente: se conservó únicamente la marca confirmada.")

    final_title = build_title(brand=final_brand, model=final_model, color=dominant_color, sku=sku)
    needs_review = not brand_is_reliable or not model_is_reliable

    return RecognitionResult(
        brand=final_brand,
        brand_confidence=brand.confidence,
        model=final_model,
        model_confidence=max(model.confidence, learned_similarity),
        title=final_title,
        sku=sku,
        needs_review=needs_review,
        method="+".join(method_parts),
        evidence=evidence,
        brand_predictions=brand_predictions,
        model_predictions=model_predictions,
        ocr_engine=ocr.engine,
    )

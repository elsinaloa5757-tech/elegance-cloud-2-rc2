from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass

import requests

BRANDS = [
    "Nike", "Jordan", "Adidas", "New Balance", "Puma", "Asics", "Converse",
    "Vans", "Reebok", "Balenciaga", "On", "Hoka", "Under Armour", "Saucony",
    "Fila", "Louis Vuitton", "Gucci", "Dior", "Hugo Boss", "Amiri",
    "Timberland", "Dr. Martens",
]
MODEL_FAMILIES = [
    "Jordan 1 Low", "Jordan 1 Mid", "Jordan 1 High", "Jordan 3", "Jordan 4",
    "Jordan 5", "Jordan 11", "Nike Dunk Low", "Nike Dunk High",
    "Nike Air Force 1", "Nike Air Max 270", "Nike Air Max 720", "Nike Air Max Dn",
    "Nike Air Max Plus TN", "Nike Air Max 90", "Nike Air Max 95",
    "Nike Air Max 97", "Nike Blazer", "Nike Cortez", "Nike Shox",
    "Nike Vapormax", "Adidas Samba", "Adidas Campus", "Adidas Gazelle",
    "Adidas Forum", "Adidas Yeezy 350", "Adidas Yeezy 500", "Adidas Yeezy 700",
    "Adidas Superstar", "Adidas NMD", "Adidas Ultraboost", "New Balance 530",
    "New Balance 550", "New Balance 9060", "New Balance 1906R",
    "New Balance 2002R", "New Balance 990", "New Balance 327", "Asics Gel",
    "On Cloud", "Hoka running shoe", "Balenciaga Speed", "Balenciaga Track",
    "Balenciaga Triple S", "Balenciaga 3XL", "Converse Chuck Taylor",
    "Vans Old Skool", "Puma Speedcat", "Puma RS-X", "Louis Vuitton Trainer",
    "Gucci Rhyton", "Dior B23", "Dior B30", "Hugo Boss sneaker",
    "Timberland 6 inch boot", "Dr. Martens boot",
]


STOPWORDS = {
    "buy","sale","shop","store","official","original","authentic","men","mens","women","womens",
    "shoe","shoes","sneaker","sneakers","trainer","trainers","footwear","black","white","grey","gray",
    "red","blue","green","brown","pink","size","sizes","price","new","online","mexico","amazon","ebay",
    "mercado","libre","aliexpress","temu","stockx","goat","review","unboxing","low","mid","high"
}

def _dynamic_consensus(page_titles: list[str]) -> tuple[str | None, int, float]:
    """Find a repeated 2-6 token product phrase across independent page titles."""
    source_phrases: list[set[str]] = []
    for title in page_titles:
        tokens = [t for t in _norm(title).split() if len(t) > 1 and t not in STOPWORDS]
        phrases: set[str] = set()
        for n in range(2, min(6, len(tokens)) + 1):
            for i in range(0, len(tokens) - n + 1):
                phrase_tokens = tokens[i:i+n]
                if not any(_norm(b) in phrase_tokens or all(x in phrase_tokens for x in _norm(b).split()) for b in BRANDS):
                    continue
                phrases.add(" ".join(phrase_tokens))
        source_phrases.append(phrases)
    counts: dict[str,int] = {}
    for phrases in source_phrases:
        for phrase in phrases:
            counts[phrase] = counts.get(phrase,0)+1
    if not counts:
        return None,0,0.0
    def score(item: tuple[str,int]) -> tuple[float,int,int]:
        phrase,hits=item
        toks=phrase.split()
        return (hits*10 + min(len(toks),5)*1.8, hits, len(toks))
    phrase,hits=max(counts.items(), key=score)
    confidence=min(1.0, 0.52 + hits*0.12 + min(len(phrase.split()),5)*0.035)
    return phrase.title(), hits, confidence


@dataclass(frozen=True)
class WebVerification:
    brand: str
    model: str
    title: str
    confidence: float
    configured: bool
    confirmed: bool
    note: str
    evidence: list[str]
    matching_sources: int = 0


def _norm(text: str) -> str:
    text = text.lower().replace("–", "-").replace("—", "-")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _best_known(texts: list[str], labels: list[str]) -> tuple[str | None, float, int]:
    """Return the best known label, its score and independent textual hits.

    A hit is counted only once per source string. This prevents one repeated entity from
    masquerading as the three independent web coincidences required for automatic approval.
    """
    normalized = [_norm(t) for t in texts if t]
    best_label: str | None = None
    best_score = 0.0
    best_hits = 0
    for label in labels:
        tokens = [t for t in _norm(label).split() if len(t) > 1]
        if not tokens:
            continue
        scores: list[float] = []
        hits = 0
        for text in normalized:
            found = sum(1 for token in tokens if token in text)
            score = found / len(tokens)
            # Require most of the identifying tokens. Generic brand-only pages do not count.
            if score >= 0.74:
                hits += 1
            scores.append(score)
        if not scores:
            continue
        top = sorted(scores, reverse=True)[:6]
        aggregate = (sum(top) / len(top)) * 0.68 + min(hits, 5) / 5 * 0.32
        if aggregate > best_score:
            best_score = aggregate
            best_label = label
            best_hits = hits
    return best_label, best_score, best_hits


def verify_with_google_vision(
    image_bytes: bytes,
    *,
    local_brand: str,
    local_model: str,
    color: str,
    api_key: str | None = None,
) -> WebVerification:
    """Verify a product by reverse-image web evidence before assigning a name.

    The local classifier is only a secondary hint. Automatic confirmation requires at least
    three independent textual web matches for the same known model family.
    """
    key = (api_key or os.getenv("GOOGLE_VISION_API_KEY", "")).strip()
    if not key:
        return WebVerification(
            brand="Sin confirmar",
            model="Modelo por confirmar",
            title="Modelo por confirmar",
            confidence=0.0,
            configured=False,
            confirmed=False,
            note=(
                "Verificación web no configurada. Agrega una Google Vision API key en "
                "Configuración. El escenario sí puede generarse, pero el producto no se "
                "publicará con un nombre adivinado."
            ),
            evidence=[],
            matching_sources=0,
        )

    endpoint = f"https://vision.googleapis.com/v1/images:annotate?key={key}"
    payload = {
        "requests": [{
            "image": {"content": base64.b64encode(image_bytes).decode("ascii")},
            "features": [{"type": "WEB_DETECTION", "maxResults": 50}],
        }]
    }
    try:
        response = requests.post(endpoint, json=payload, timeout=45)
        response.raise_for_status()
        body = response.json()
        result = body.get("responses", [{}])[0]
        if result.get("error"):
            raise RuntimeError(result["error"].get("message", "Google Vision devolvió un error"))
        web = result.get("webDetection", {})

        # Keep page titles as independent sources. Entities and best guesses support scoring,
        # but they do not alone satisfy the minimum-three-source publication rule.
        page_titles: list[str] = []
        supporting_texts: list[str] = []
        evidence: list[str] = []

        for item in web.get("pagesWithMatchingImages", []) or []:
            title = re.sub(r"<[^>]+>", " ", str(item.get("pageTitle", ""))).strip()
            url = str(item.get("url", "")).strip()
            if title:
                page_titles.append(title)
                supporting_texts.append(title)
                evidence.append(f"{title} — {url}" if url else title)

        for item in web.get("bestGuessLabels", []) or []:
            label = str(item.get("label", "")).strip()
            if label:
                supporting_texts.append(label)
                evidence.append(label)

        for item in web.get("webEntities", []) or []:
            desc = str(item.get("description", "")).strip()
            score = float(item.get("score", 0) or 0)
            if desc:
                supporting_texts.extend([desc] * (2 if score >= 0.65 else 1))
                evidence.append(desc)

        # First decide from independent page-title coincidences. Supporting entities can raise
        # confidence but cannot replace the required three matching sources.
        page_model, page_score, page_hits = _best_known(page_titles, MODEL_FAMILIES)
        support_model, support_score, _ = _best_known(supporting_texts, MODEL_FAMILIES)
        dynamic_model, dynamic_hits, dynamic_score = _dynamic_consensus(page_titles)
        if dynamic_model and dynamic_hits >= max(3, page_hits) and dynamic_score >= page_score:
            model_label = dynamic_model
            model_score = dynamic_score
            page_hits = dynamic_hits
            page_model = dynamic_model
        else:
            model_label = page_model if page_model and page_hits >= 1 else support_model
            model_score = max(page_score, support_score * 0.90)

        brand_label, brand_score, brand_hits = _best_known(
            supporting_texts, [b for b in BRANDS if b != "Unknown"]
        )

        # Keep model and brand internally consistent.
        if model_label:
            model_norm = _norm(model_label)
            for known_brand in BRANDS:
                if _norm(known_brand) in model_norm:
                    brand_label = known_brand
                    brand_score = max(brand_score, model_score * 0.95)
                    break

        matching_sources = page_hits if page_model == model_label else 0
        consensus = min(
            1.0,
            model_score * 0.74
            + brand_score * 0.16
            + min(matching_sources, 3) / 3 * 0.10,
        )
        confirmed = bool(model_label) and matching_sources >= 3 and consensus >= 0.78

        if confirmed:
            clean_model = model_label or "Modelo por confirmar"
            clean_brand = brand_label or "Sin confirmar"
            title = " ".join(x for x in [clean_model, color] if x).strip()
            note = (
                f"Confirmado automáticamente con {matching_sources} coincidencias web "
                f"independientes para el mismo modelo."
            )
        else:
            clean_model = "Modelo por confirmar"
            clean_brand = brand_label or (local_brand if local_brand != "Unknown" else "Sin confirmar")
            title = "Modelo por confirmar"
            note = (
                f"Se encontraron {matching_sources} de 3 coincidencias web requeridas. "
                "No se asignó un nombre definitivo ni se publicará automáticamente."
            )

        return WebVerification(
            brand=clean_brand,
            model=clean_model,
            title=title,
            confidence=round(consensus, 4),
            configured=True,
            confirmed=confirmed,
            note=note,
            evidence=list(dict.fromkeys(evidence))[:20],
            matching_sources=matching_sources,
        )
    except Exception as exc:
        return WebVerification(
            brand="Sin confirmar",
            model="Modelo por confirmar",
            title="Modelo por confirmar",
            confidence=0.0,
            configured=True,
            confirmed=False,
            note=f"No fue posible completar la verificación web: {exc}",
            evidence=[],
            matching_sources=0,
        )

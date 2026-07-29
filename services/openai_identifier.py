from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"
CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "identifications"
CACHE_TTL_SECONDS = 60 * 60 * 24 * 120


@dataclass(frozen=True)
class IdentificationResult:
    brand: str
    model: str
    title: str
    color: str
    confidence: float
    configured: bool
    confirmed: bool
    matching_sources: int
    note: str
    evidence: list[str]
    engine: str
    sku: str = ""
    colorway: str = ""
    cache_hit: bool = False


def _extract_output_text(payload: dict) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    parts: list[str] = []
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def _extract_citations(payload: dict) -> list[str]:
    citations: list[str] = []
    seen_domains: set[str] = set()
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            for ann in content.get("annotations", []) or []:
                if ann.get("type") != "url_citation":
                    continue
                url = str(ann.get("url") or "").strip()
                title = str(ann.get("title") or "").strip()
                domain = urlparse(url).netloc.lower().removeprefix("www.")
                if not url or not domain or domain in seen_domains:
                    continue
                seen_domains.add(domain)
                citations.append(f"{title} — {domain} — {url}" if title else f"{domain} — {url}")
    return citations


def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)


def _post(payload: dict, key: str, timeout_seconds: int) -> dict:
    response = requests.post(
        RESPONSES_ENDPOINT,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message", response.text)
        except Exception:
            detail = response.text
        raise RuntimeError(f"OpenAI Responses {response.status_code}: {detail}")
    return response.json()


def _cache_path(image_bytes: bytes, model: str) -> Path:
    digest = hashlib.sha256(image_bytes).hexdigest()
    safe_model = re.sub(r"[^a-zA-Z0-9._-]+", "_", model)
    return CACHE_DIR / f"{digest}_{safe_model}.json"


def _load_cache(path: Path) -> IdentificationResult | None:
    try:
        if not path.exists() or time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        data["cache_hit"] = True
        return IdentificationResult(**data)
    except Exception:
        return None


def _save_cache(path: Path, result: IdentificationResult) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(result)
        payload["cache_hit"] = False
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def identify_with_openai_web(
    image_bytes: bytes,
    *,
    api_key: str | None,
    model: str = "gpt-5.6",
    local_brand: str = "",
    local_model: str = "",
    color: str = "",
    timeout_seconds: int = 210,
) -> IdentificationResult:
    key = (api_key or os.getenv("OPENAI_API_KEY", "")).strip()
    if not key:
        return IdentificationResult(
            brand="Sin confirmar", model="Modelo por confirmar", title="Modelo por confirmar",
            color=color, confidence=0.0, configured=False, confirmed=False,
            matching_sources=0, note="Configura OpenAI para identificación visual y búsqueda web.",
            evidence=[], engine="none",
        )

    selected_model = model or "gpt-5.6"
    cache_file = _cache_path(image_bytes, selected_model)
    cached = _load_cache(cache_file)
    if cached is not None:
        return cached

    b64 = base64.b64encode(image_bytes).decode("ascii")
    weak_hints = f"marca local={local_brand or 'ninguna'}, familia local={local_model or 'ninguna'}, color local={color or 'ninguno'}"

    visual_prompt = f"""
Actúa como especialista en identificación de sneakers y botas. Analiza SOLO la imagen.
Las pistas locales son débiles y pueden estar equivocadas: {weak_hints}.

Describe señales verificables: logotipo, silueta, patrón de paneles, mediasuela, unidad de aire,
suela, lengüeta, ojales, materiales y cualquier SKU o texto legible. Propón como máximo 5 candidatos
ordenados. No inventes SKU ni colorway. Devuelve únicamente JSON válido:
{{
  "visual_brand": "Jordan",
  "visual_type": "sneaker de básquetbol retro",
  "visible_text": ["AIR"],
  "distinctive_features": ["..."],
  "candidates": [
    {{"brand":"Jordan","model":"Air Jordan 3 Retro","confidence":0.86,"reason":"..."}}
  ]
}}
""".strip()
    visual_payload = {
        "model": selected_model,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": visual_prompt},
                {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}"},
            ],
        }],
    }

    try:
        visual_response = _post(visual_payload, key, timeout_seconds)
        visual = _parse_json(_extract_output_text(visual_response))
        candidates = visual.get("candidates") or []
        candidate_lines = []
        for candidate in candidates[:5]:
            candidate_lines.append(
                f"- {candidate.get('brand','')} {candidate.get('model','')} "
                f"(confianza visual {candidate.get('confidence',0)}): {candidate.get('reason','')}"
            )
        features = "; ".join(str(x) for x in (visual.get("distinctive_features") or [])[:12])
        visible_text = ", ".join(str(x) for x in (visual.get("visible_text") or [])[:12])

        verify_prompt = f"""
Verifica en la web la identidad exacta del calzado descrito abajo. No uses una sola tienda ni copies
un título aislado. Compara imágenes, silueta y detalles. Prioriza fabricante oficial y comercios/editoriales
reconocidos. Cuenta como fuente independiente solo un dominio distinto.

ANÁLISIS VISUAL:
Marca visual: {visual.get('visual_brand','')}
Tipo: {visual.get('visual_type','')}
Texto visible: {visible_text}
Rasgos: {features}
Candidatos:
{chr(10).join(candidate_lines) if candidate_lines else '- Ninguno confiable'}

Reglas:
1. Busca y contrasta los candidatos y alternativas cercanas.
2. Exige al menos 3 dominios independientes que coincidan en marca y familia/modelo.
3. El SKU y colorway solo pueden confirmarse si aparecen coincidentes en al menos 2 fuentes fiables.
4. Si solo se confirma la familia (por ejemplo Air Jordan 3 Retro) devuelve esa familia; no inventes edición.
5. Si no hay consenso suficiente, confirmed=false y title/model="Modelo por confirmar".

Devuelve únicamente JSON válido:
{{
  "brand":"Jordan",
  "model":"Air Jordan 3 Retro",
  "title":"Air Jordan 3 Retro",
  "sku":"",
  "colorway":"",
  "color":"blanco / gris cemento",
  "confidence":0.93,
  "confirmed":true,
  "matching_sources":3,
  "note":"explicación breve del consenso"
}}
""".strip()
        verify_payload = {
            "model": selected_model,
            "tools": [{"type": "web_search"}],
            "input": [{"role": "user", "content": [{"type": "input_text", "text": verify_prompt}]}],
        }
        web_response = _post(verify_payload, key, timeout_seconds)
        data = _parse_json(_extract_output_text(web_response))
        citations = _extract_citations(web_response)
        reported_sources = int(data.get("matching_sources", 0) or 0)
        actual_sources = len(citations)
        sources = min(reported_sources, actual_sources) if actual_sources else 0
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0) or 0)))
        strict_consensus = bool(data.get("confirmed")) and sources >= 3 and confidence >= 0.80
        strong_consensus = sources >= 2 and confidence >= 0.88
        decisive_match = sources >= 1 and confidence >= 0.95
        confirmed = strict_consensus or strong_consensus or decisive_match

        brand = str(data.get("brand") or visual.get("visual_brand") or "Sin confirmar").strip()
        model_name = str(data.get("model") or "Modelo por confirmar").strip()
        title = str(data.get("title") or model_name).strip()
        sku = str(data.get("sku") or "").strip()
        colorway = str(data.get("colorway") or "").strip()
        # Conserva la mejor identificación aunque todavía sea una sugerencia. Esto evita
        # reemplazar un nombre útil por “Modelo por confirmar” y permite una segunda revisión.
        if not model_name or model_name.lower() in {"unknown", "other sneaker"}:
            model_name = "Modelo por confirmar"
        if not title or title.lower() in {"unknown", "other sneaker"}:
            title = model_name
        if not confirmed:
            sku = ""
            colorway = ""

        result = IdentificationResult(
            brand=brand,
            model=model_name,
            title=title,
            color=str(data.get("color") or color).strip(),
            confidence=round(confidence, 4),
            configured=True,
            confirmed=confirmed,
            matching_sources=sources,
            note=(str(data.get("note") or "").strip() + (
                " Confirmación automática por consenso fuerte." if confirmed and not strict_consensus else
                " Coincidencia probable conservada para revisión." if not confirmed else ""
            )).strip(),
            evidence=citations[:10],
            engine=selected_model,
            sku=sku,
            colorway=colorway,
            cache_hit=False,
        )
        _save_cache(cache_file, result)
        return result
    except Exception as exc:
        return IdentificationResult(
            brand="Sin confirmar", model="Modelo por confirmar", title="Modelo por confirmar",
            color=color, confidence=0.0, configured=True, confirmed=False,
            matching_sources=0, note=f"No fue posible completar la identificación: {exc}",
            evidence=[], engine=selected_model,
        )

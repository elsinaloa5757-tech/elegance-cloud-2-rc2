from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    model: str
    model_loaded: bool
    device: str


class Prediction(BaseModel):
    label: str
    confidence: float = Field(ge=0.0, le=1.0)


class ImageMetadata(BaseModel):
    index: int
    filename: str
    duplicate: bool
    duplicate_of: int | None = None
    dominant_color: str
    dominant_rgb: list[int]
    sharpness: float
    quality_score: float
    quality_label: str
    width: int
    height: int


class GroupItem(BaseModel):
    index: int
    filename: str
    confidence: float = Field(ge=0.0, le=1.0)
    is_cover: bool


class ProductGroup(BaseModel):
    group_id: int
    count: int
    cover_index: int
    average_confidence: float
    dominant_color: str

    brand: str
    brand_confidence: float

    model_family: str
    model_confidence: float

    shoe_type: str
    type_confidence: float

    material: str
    material_confidence: float

    suggested_title: str
    needs_manual_review: bool
    sku: str = ""
    identification_method: str = ""
    identification_evidence: list[str] = Field(default_factory=list)
    ocr_engine: str = ""

    brand_predictions: list[Prediction]
    model_predictions: list[Prediction]

    items: list[GroupItem]


class AnalyzeResponse(BaseModel):
    status: str
    engine: str
    model: str
    device: str
    images_received: int
    unique_images: int
    duplicate_images: int
    groups_found: int
    parameters: dict[str, float | int]
    groups: list[ProductGroup]
    images: list[ImageMetadata]
    warning: str

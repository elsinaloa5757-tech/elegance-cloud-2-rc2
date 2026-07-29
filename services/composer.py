from __future__ import annotations

from io import BytesIO
from pathlib import Path
import hashlib

import cv2
import numpy as np
from PIL import Image

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
SCENARIO_PATH = ASSETS_DIR / "elegance_scenario_clean.png"
LEGACY_SCENARIO_PATH = ASSETS_DIR / "elegance_scenario_official.png"


def _try_rembg(data: bytes) -> np.ndarray | None:
    """Use a neural foreground mask when rembg/onnxruntime is available."""
    try:
        from rembg import remove  # type: ignore

        output = remove(
            data,
            alpha_matting=True,
            alpha_matting_foreground_threshold=235,
            alpha_matting_background_threshold=20,
            alpha_matting_erode_size=8,
        )
        pil = Image.open(BytesIO(output)).convert("RGBA")
        rgba = np.asarray(pil)
        # PIL RGBA -> OpenCV BGRA
        return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
    except Exception:
        return None


def _largest_useful_components(alpha: np.ndarray) -> np.ndarray:
    binary = (alpha > 30).astype(np.uint8)
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, 8)
    if count <= 1:
        return alpha

    h, w = alpha.shape
    center = np.array([w * 0.52, h * 0.58])
    candidates: list[tuple[float, int]] = []
    for idx in range(1, count):
        area = float(stats[idx, cv2.CC_STAT_AREA])
        if area < h * w * 0.006:
            continue
        cx, cy = centroids[idx]
        distance = np.linalg.norm((np.array([cx, cy]) - center) / np.array([w, h]))
        bottom_bonus = 0.18 if cy > h * 0.48 else 0.0
        score = area / (h * w) - distance * 0.16 + bottom_bonus
        candidates.append((score, idx))

    if not candidates:
        return alpha
    candidates.sort(reverse=True)
    keep = [idx for _, idx in candidates[:2]]
    result = np.zeros_like(alpha)
    for idx in keep:
        result[labels == idx] = alpha[labels == idx]
    return result


def _grabcut_alpha(bgr: np.ndarray) -> np.ndarray:
    """Conservative segmentation tuned for supplier photos of shoes held by hand."""
    h, w = bgr.shape[:2]
    max_side = 1400
    scale = min(1.0, max_side / max(h, w))
    work = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else bgr.copy()
    wh, ww = work.shape[:2]

    mask = np.full((wh, ww), cv2.GC_PR_BGD, np.uint8)
    border_x = max(4, int(ww * 0.035))
    border_y = max(4, int(wh * 0.035))
    mask[:border_y, :] = cv2.GC_BGD
    mask[-border_y:, :] = cv2.GC_BGD
    mask[:, :border_x] = cv2.GC_BGD
    mask[:, -border_x:] = cv2.GC_BGD

    # Product/hand normally occupies the center and lower half.
    ellipse = np.zeros((wh, ww), np.uint8)
    cv2.ellipse(
        ellipse,
        (int(ww * 0.53), int(wh * 0.58)),
        (int(ww * 0.43), int(wh * 0.39)),
        0,
        0,
        360,
        255,
        -1,
    )
    mask[ellipse > 0] = cv2.GC_PR_FGD

    # Strong edges inside the central region become foreground seeds.
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 45, 135)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)
    mask[(edges > 0) & (ellipse > 0)] = cv2.GC_FGD

    # Preserve visible hands connected to the product.
    hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
    skin = cv2.inRange(hsv, np.array([0, 22, 45]), np.array([28, 190, 255]))
    skin = cv2.morphologyEx(skin, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=2)
    lower = np.zeros_like(skin)
    lower[int(wh * 0.34):, :] = 255
    mask[(skin > 0) & (lower > 0)] = cv2.GC_PR_FGD

    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(work, mask, None, bgd, fgd, 9, cv2.GC_INIT_WITH_MASK)
        alpha = np.where(
            (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0
        ).astype(np.uint8)
    except Exception as exc:
        raise ValueError(f"No se pudo segmentar el producto: {exc}") from exc

    alpha = _largest_useful_components(alpha)
    kernel = np.ones((5, 5), np.uint8)
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, kernel, iterations=2)
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
    alpha = cv2.GaussianBlur(alpha, (0, 0), 1.7)

    ratio = float((alpha > 25).mean())
    if ratio < 0.045 or ratio > 0.78:
        raise ValueError("La segmentación no fue confiable; prueba otra vista del producto")

    if scale < 1:
        alpha = cv2.resize(alpha, (w, h), interpolation=cv2.INTER_LINEAR)
    return alpha


def _segment(data: bytes, source: np.ndarray) -> tuple[np.ndarray, str]:
    neural = _try_rembg(data)
    if neural is not None:
        neural[:, :, 3] = _largest_useful_components(neural[:, :, 3])
        if 0.04 < float((neural[:, :, 3] > 25).mean()) < 0.80:
            return neural, "rembg"

    alpha = _grabcut_alpha(source)
    rgba = cv2.cvtColor(source, cv2.COLOR_BGR2BGRA)
    rgba[:, :, 3] = alpha
    return rgba, "grabcut"


def _crop_to_alpha(rgba: np.ndarray) -> np.ndarray:
    alpha = rgba[:, :, 3]
    points = cv2.findNonZero((alpha > 18).astype(np.uint8))
    if points is None:
        return rgba
    x, y, w, h = cv2.boundingRect(points)
    pad_x = max(5, int(w * 0.035))
    pad_y = max(5, int(h * 0.035))
    return rgba[
        max(0, y - pad_y): min(rgba.shape[0], y + h + pad_y),
        max(0, x - pad_x): min(rgba.shape[1], x + w + pad_x),
    ]


def _brand_style(brand: str) -> dict[str, object]:
    key = brand.lower().strip()
    if "jordan" in key:
        return {"tint": (25, 38, 72), "offset": -0.03, "contrast": 1.10, "blue": 0.12}
    if "adidas" in key or "yeezy" in key:
        return {"tint": (38, 50, 58), "offset": 0.04, "contrast": 0.96, "blue": 0.06}
    if "new balance" in key:
        return {"tint": (28, 55, 72), "offset": 0.02, "contrast": 1.02, "blue": 0.08}
    if key == "on" or "hoka" in key:
        return {"tint": (52, 68, 76), "offset": 0.05, "contrast": 1.00, "blue": 0.05}
    if any(x in key for x in ["balenciaga", "dior", "gucci", "boss", "louis vuitton"]):
        return {"tint": (18, 28, 46), "offset": -0.02, "contrast": 1.14, "blue": 0.08}
    if any(x in key for x in ["bota", "timberland", "martens"]):
        return {"tint": (28, 46, 58), "offset": 0.01, "contrast": 1.04, "blue": 0.04}
    return {"tint": (24, 62, 92), "offset": 0.0, "contrast": 1.05, "blue": 0.10}


def _load_scene() -> np.ndarray:
    path = SCENARIO_PATH if SCENARIO_PATH.exists() else LEGACY_SCENARIO_PATH
    scene = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if scene is None:
        raise RuntimeError("No se encontró el escenario oficial")
    return scene


def _grade_scene(scene: np.ndarray, brand_theme: str) -> np.ndarray:
    style = _brand_style(brand_theme)
    tint = np.asarray(style["tint"], dtype=np.uint8)
    overlay = np.full_like(scene, tint)
    graded = cv2.addWeighted(scene, 0.91, overlay, 0.09, 0)
    contrast = float(style["contrast"])
    graded = np.clip((graded.astype(np.float32) - 118.0) * contrast + 118.0, 0, 255).astype(np.uint8)

    # Brand variation changes the viewpoint subtly instead of reusing an identical frame.
    offset = int(scene.shape[1] * float(style["offset"]))
    if offset:
        graded = np.roll(graded, offset, axis=1)
    return graded


def _match_subject_to_scene(fg_bgr: np.ndarray, alpha: np.ndarray, roi: np.ndarray, blue_strength: float) -> np.ndarray:
    subject = fg_bgr.astype(np.float32)
    visible = alpha > 40
    if visible.any():
        subj_lab = cv2.cvtColor(np.clip(subject, 0, 255).astype(np.uint8), cv2.COLOR_BGR2LAB).astype(np.float32)
        roi_lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB).astype(np.float32)
        s_mean = subj_lab[visible].mean(axis=0)
        r_mean = roi_lab.reshape(-1, 3).mean(axis=0)
        # Match luminance conservatively; preserve product color identity.
        delta_l = np.clip((r_mean[0] - s_mean[0]) * 0.32, -24, 20)
        subj_lab[:, :, 0] = np.clip(subj_lab[:, :, 0] + delta_l, 0, 255)
        subject = cv2.cvtColor(subj_lab.astype(np.uint8), cv2.COLOR_LAB2BGR).astype(np.float32)

    # Add a subtle ice-blue bounce light from the environment.
    blue = np.zeros_like(subject)
    blue[:, :, 0] = 255
    blue[:, :, 1] = 205
    blue[:, :, 2] = 95
    subject = np.clip(subject * (1.0 - blue_strength * 0.08) + blue * (blue_strength * 0.08), 0, 255)
    return subject


def _silhouette_shadow(alpha: np.ndarray, output_shape: tuple[int, int], x: int, y: int) -> np.ndarray:
    sh, sw = output_shape
    shadow = np.zeros((sh, sw), np.uint8)
    ah, aw = alpha.shape
    # Project the lower silhouette onto the floor for a more natural contact shadow.
    lower = alpha.copy()
    lower[: int(ah * 0.58), :] = 0
    lower = cv2.resize(lower, (aw, max(4, int(ah * 0.17))), interpolation=cv2.INTER_AREA)
    lower = cv2.GaussianBlur(lower, (0, 0), sigmaX=max(5, aw * 0.025), sigmaY=max(3, ah * 0.012))
    sy = min(sh - lower.shape[0], y + ah - int(ah * 0.06))
    sx = max(0, min(sw - aw, x))
    shadow[sy:sy + lower.shape[0], sx:sx + aw] = np.maximum(
        shadow[sy:sy + lower.shape[0], sx:sx + aw],
        (lower.astype(np.float32) * 0.58).astype(np.uint8),
    )
    return shadow


def compose_product(data: bytes, brand_theme: str = "Automático") -> bytes:
    source = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if source is None:
        raise ValueError("No se pudo decodificar la imagen")

    rgba, _engine = _segment(data, source)
    rgba = _crop_to_alpha(rgba)
    scene = _grade_scene(_load_scene(), brand_theme)

    sh, sw = scene.shape[:2]
    fh, fw = rgba.shape[:2]
    key = brand_theme.lower()
    is_boot = any(x in key for x in ["bota", "timberland", "martens", "boot"]) or fh > fw * 1.08
    has_hand = bool(np.count_nonzero(rgba[int(fh * 0.72):, :, 3] > 50) > fw * fh * 0.018)

    target_w = int(sw * (0.50 if is_boot else 0.61))
    target_h = int(sh * (0.58 if is_boot else 0.49))
    scale = min(target_w / max(fw, 1), target_h / max(fh, 1))
    new_w, new_h = max(1, int(fw * scale)), max(1, int(fh * scale))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    fg = cv2.resize(rgba, (new_w, new_h), interpolation=interpolation)

    style = _brand_style(brand_theme)
    x = int((sw - new_w) * (0.50 + float(style["offset"]) * 0.55))
    x = max(0, min(sw - new_w, x))
    bottom = int(sh * (0.91 if has_hand else 0.86))
    y = max(0, min(sh - new_h, bottom - new_h))

    alpha = fg[:, :, 3]
    shadow = _silhouette_shadow(alpha, (sh, sw), x, y)
    shade = 1.0 - (shadow.astype(np.float32) / 255.0) * 0.50
    scene = np.clip(scene.astype(np.float32) * shade[:, :, None], 0, 255).astype(np.uint8)

    roi = scene[y:y + new_h, x:x + new_w]
    fg_bgr = _match_subject_to_scene(
        fg[:, :, :3], alpha, roi, float(style["blue"])
    )
    a = alpha.astype(np.float32)[:, :, None] / 255.0

    # Rim light follows the real silhouette rather than a rectangular crop.
    rim = cv2.dilate(alpha, np.ones((5, 5), np.uint8), iterations=1) - alpha
    rim = cv2.GaussianBlur(rim, (0, 0), 2.2).astype(np.float32) / 255.0
    rim_color = np.zeros_like(fg_bgr)
    rim_color[:, :, 0] = 255
    rim_color[:, :, 1] = 210
    rim_color[:, :, 2] = 100
    fg_bgr = np.clip(fg_bgr + rim[:, :, None] * rim_color * 0.20, 0, 255)

    composed = fg_bgr * a + roi.astype(np.float32) * (1.0 - a)
    scene[y:y + new_h, x:x + new_w] = composed.astype(np.uint8)

    # Mild depth-of-field vignette keeps attention on the product.
    vignette = np.ones((sh, sw), np.float32)
    cv2.ellipse(vignette, (sw // 2, int(sh * 0.62)), (int(sw * 0.46), int(sh * 0.43)), 0, 0, 360, 0.0, -1)
    vignette = cv2.GaussianBlur(vignette, (0, 0), sigmaX=sw * 0.16)
    darken = 1.0 - vignette * 0.13
    scene = np.clip(scene.astype(np.float32) * darken[:, :, None], 0, 255).astype(np.uint8)

    ok, encoded = cv2.imencode(".png", scene, [cv2.IMWRITE_PNG_COMPRESSION, 4])
    if not ok:
        raise RuntimeError("No se pudo exportar la composición")
    return encoded.tobytes()

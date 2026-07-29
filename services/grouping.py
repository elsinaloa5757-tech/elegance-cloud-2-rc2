from __future__ import annotations
from collections import defaultdict
import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_similarity

def _rgb_distance(a: list[int], b: list[int]) -> float:
    return float(np.linalg.norm(np.asarray(a, dtype=np.float32) - np.asarray(b, dtype=np.float32)))

def cluster_embeddings(embeddings: np.ndarray, colors_rgb: list[list[int]], *, distance_threshold: float, color_threshold: float) -> list[list[int]]:
    if len(embeddings) == 0:
        return []
    if len(embeddings) == 1:
        return [[0]]
    labels = AgglomerativeClustering(
        n_clusters=None,
        metric="cosine",
        linkage="average",
        distance_threshold=distance_threshold,
    ).fit_predict(embeddings)
    raw = defaultdict(list)
    for i, label in enumerate(labels.tolist()):
        raw[label].append(i)
    result = []
    for indices in raw.values():
        locals_ = []
        for i in indices:
            placed = False
            for group in locals_:
                if _rgb_distance(colors_rgb[i], colors_rgb[group[0]]) <= color_threshold:
                    group.append(i)
                    placed = True
                    break
            if not placed:
                locals_.append([i])
        result.extend(locals_)
    return sorted(result, key=lambda g: min(g))

def group_confidences(embeddings: np.ndarray, indices: list[int]) -> list[float]:
    if len(indices) == 1:
        return [1.0]
    selected = embeddings[indices]
    centroid = selected.mean(axis=0, keepdims=True)
    centroid /= np.clip(np.linalg.norm(centroid, axis=1, keepdims=True), 1e-12, None)
    sims = cosine_similarity(selected, centroid).reshape(-1)
    return [round(float(np.clip(v, 0.0, 1.0)), 4) for v in sims]

def visual_duplicate_pairs(embeddings: np.ndarray, threshold: float = 0.9985) -> dict[int, int]:
    if len(embeddings) < 2:
        return {}
    sims = cosine_similarity(embeddings)
    duplicates = {}
    for i in range(len(embeddings)):
        for j in range(i):
            if sims[i, j] >= threshold:
                duplicates[i] = j
                break
    return duplicates

def representative_index(embeddings: np.ndarray, indices: list[int], sharpness: list[float]) -> int:
    if len(indices) == 1:
        return indices[0]
    selected = embeddings[indices]
    centrality = cosine_similarity(selected).mean(axis=1)
    sharp = np.asarray([sharpness[i] for i in indices], dtype=np.float32)
    if sharp.max() > sharp.min():
        sharp = (sharp - sharp.min()) / (sharp.max() - sharp.min())
    else:
        sharp = np.ones_like(sharp)
    score = centrality * 0.78 + sharp * 0.22
    return indices[int(np.argmax(score))]

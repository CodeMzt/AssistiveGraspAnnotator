"""Shared mask candidate artifact helpers.

This module intentionally contains no RGB/HSV teacher implementation. Only SAM-family candidate versions are accepted by the web backend.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


SAM_ALGORITHM_PREFIX = "sam2_"
DEFAULT_SAM_ALGORITHM_VERSION = "sam2_box_prompt_v1"


def object_signature(annotation: dict[str, Any], obj: dict[str, Any]) -> str:
    payload = {
        "image_id": annotation.get("image_id", ""),
        "width": int(annotation.get("width") or 0),
        "height": int(annotation.get("height") or 0),
        "instance_id": int(obj.get("instance_id") or 0),
        "class_id": int(obj.get("class_id") or 0),
        "class_name": str(obj.get("class_name") or ""),
        "bbox_xyxy": [round(float(v), 3) for v in obj.get("bbox_xyxy", [])],
        "main_axis_points": obj.get("main_axis_points") or None,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def is_supported_mask_candidate(candidate: dict[str, Any] | None) -> bool:
    if not candidate:
        return False
    version = str(candidate.get("algorithm_version") or "")
    return version.startswith(SAM_ALGORITHM_PREFIX)


def clamp_bbox(values: list[Any], width: int, height: int) -> list[int]:
    x1, y1, x2, y2 = [float(v) for v in values[:4]]
    left = max(0, min(width - 1, int(math.floor(min(x1, x2)))))
    top = max(0, min(height - 1, int(math.floor(min(y1, y2)))))
    right = max(left + 1, min(width, int(math.ceil(max(x1, x2)))))
    bottom = max(top + 1, min(height, int(math.ceil(max(y1, y2)))))
    return [left, top, right, bottom]


def build_mask_candidate_payload(
    *,
    image_path: Path,
    annotation: dict[str, Any],
    obj: dict[str, Any],
    artifact_dir: Path,
    full_mask: np.ndarray,
    algorithm_version: str = DEFAULT_SAM_ALGORITHM_VERSION,
    source: str = "sam2_teacher",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    bbox = clamp_bbox(obj.get("bbox_xyxy", [0, 0, width, height]), width, height)
    mask = _normalize_mask(full_mask, width, height)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    signature = object_signature(annotation, obj)
    stable_extra = json.dumps(extra or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    candidate_id = hashlib.sha1(
        f"{annotation.get('image_id')}:{obj.get('instance_id')}:{signature}:{algorithm_version}:{stable_extra}".encode("utf-8")
    ).hexdigest()[:16]
    safe_version = _safe_stem(algorithm_version)
    stem = f"obj_{int(obj.get('instance_id') or 0):03d}.{safe_version}.{candidate_id}"
    mask_path = artifact_dir / f"{stem}.mask.png"
    preview_path = artifact_dir / f"{stem}.preview.png"
    Image.fromarray(mask, mode="L").save(mask_path)
    write_preview(mask, preview_path)

    contour = smooth_contour(mask, bbox)
    payload = {
        "schema_version": "mask_candidate_v1",
        "candidate_id": candidate_id,
        "source": source,
        "algorithm_version": algorithm_version,
        "image_id": annotation.get("image_id", ""),
        "instance_id": int(obj.get("instance_id") or 0),
        "class_id": int(obj.get("class_id") or 0),
        "class_name": str(obj.get("class_name") or ""),
        "bbox_xyxy": [float(v) for v in bbox],
        "roi_xyxy": _mask_roi(mask, bbox),
        "annotation_signature": signature,
        "mask_origin_xy": [0, 0],
        "mask_size": [int(width), int(height)],
        "mask_png": str(mask_path.name),
        "preview_png": str(preview_path.name),
        "smooth_contour_px": contour,
        "anchor_px": mask_anchor(mask, bbox),
        "area_px": int((mask > 0).sum()),
        "quality_auto_score": auto_quality_score(mask, bbox, contour),
    }
    if extra:
        payload.update(extra)
    return payload


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        Path(tmp_name).replace(path)
    except Exception:
        try:
            Path(tmp_name).unlink(missing_ok=True)
        finally:
            raise


def mask_anchor(mask: np.ndarray, bbox: list[int]) -> list[float]:
    ys, xs = np.nonzero(mask > 0)
    if len(xs) == 0:
        return [(bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0]
    return [round(float(xs.mean()), 3), round(float(ys.mean()), 3)]


def smooth_contour(mask: np.ndarray, bbox: list[int], bins: int = 256) -> list[list[float]]:
    ys, xs = np.nonzero(mask > 0)
    if len(xs) < 16:
        return rounded_bbox_contour(bbox, bins)
    eroded = erode(mask > 0, iterations=1)
    boundary = (mask > 0) & ~eroded
    by, bx = np.nonzero(boundary)
    if len(bx) < 16:
        return rounded_bbox_contour(bbox, bins)

    cx = float(xs.mean())
    cy = float(ys.mean())
    angles = np.arctan2(by - cy, bx - cx)
    radii = np.hypot(bx - cx, by - cy)
    bin_ids = np.floor(((angles + math.pi) / (2 * math.pi)) * bins).astype(int) % bins
    radial = np.full(bins, np.nan, dtype=np.float32)
    for index in range(len(bx)):
        bin_id = int(bin_ids[index])
        if np.isnan(radial[bin_id]) or radii[index] > radial[bin_id]:
            radial[bin_id] = radii[index]

    valid = np.where(~np.isnan(radial))[0]
    if valid.size < 8:
        return rounded_bbox_contour(bbox, bins)
    for i in range(bins):
        if not np.isnan(radial[i]):
            continue
        prev_candidates = valid[valid < i]
        next_candidates = valid[valid > i]
        prev_i = int(prev_candidates[-1]) if prev_candidates.size else int(valid[-1] - bins)
        next_i = int(next_candidates[0]) if next_candidates.size else int(valid[0] + bins)
        prev_r = radial[prev_i % bins]
        next_r = radial[next_i % bins]
        t = (i - prev_i) / max(1, next_i - prev_i)
        radial[i] = float(prev_r * (1 - t) + next_r * t)

    smooth = radial.copy()
    kernel = np.array([1, 2, 4, 6, 4, 2, 1], dtype=np.float32)
    kernel /= kernel.sum()
    half = len(kernel) // 2
    for i in range(bins):
        values = np.array([radial[(i + k - half) % bins] for k in range(len(kernel))], dtype=np.float32)
        smooth[i] = float((values * kernel).sum())

    result: list[list[float]] = []
    for i, radius in enumerate(smooth):
        theta = -math.pi + (2 * math.pi * i / bins)
        result.append([round(cx + math.cos(theta) * float(radius), 3), round(cy + math.sin(theta) * float(radius), 3)])
    return result


def rounded_bbox_contour(bbox: list[int], bins: int) -> list[list[float]]:
    x1, y1, x2, y2 = bbox
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    rx = max(1.0, (x2 - x1) / 2.0)
    ry = max(1.0, (y2 - y1) / 2.0)
    return [
        [round(cx + math.cos(2 * math.pi * i / bins) * rx, 3), round(cy + math.sin(2 * math.pi * i / bins) * ry, 3)]
        for i in range(bins)
    ]


def auto_quality_score(mask: np.ndarray, bbox: list[int], contour: list[list[float]]) -> float:
    x1, y1, x2, y2 = bbox
    bbox_area = max(1, (x2 - x1) * (y2 - y1))
    fill = float((mask > 0).sum()) / float(bbox_area)
    if not contour or fill < 0.04 or fill > 1.50:
        return 1.0
    if fill < 0.10 or fill > 1.20:
        return 2.0
    if fill < 0.18 or fill > 0.98:
        return 3.0
    return 4.0


def write_preview(mask: np.ndarray, path: Path) -> None:
    rgba = np.zeros((mask.shape[0], mask.shape[1], 4), dtype=np.uint8)
    rgba[..., 0] = 17
    rgba[..., 1] = 128
    rgba[..., 2] = 105
    rgba[..., 3] = np.where(mask > 0, 96, 0).astype(np.uint8)
    Image.fromarray(rgba, mode="RGBA").save(path)


def erode(mask: np.ndarray, iterations: int = 1) -> np.ndarray:
    out = mask.astype(bool)
    for _ in range(iterations):
        padded = np.pad(out, 1, mode="constant", constant_values=False)
        acc = np.ones_like(out)
        for dy in range(3):
            for dx in range(3):
                acc &= padded[dy:dy + out.shape[0], dx:dx + out.shape[1]]
        out = acc
    return out


def _normalize_mask(mask: np.ndarray, width: int, height: int) -> np.ndarray:
    arr = np.asarray(mask)
    if arr.shape != (height, width):
        raise ValueError(f"Mask shape {arr.shape} does not match image size {(height, width)}")
    if arr.dtype == bool:
        return arr.astype(np.uint8) * 255
    return np.where(arr > 0, 255, 0).astype(np.uint8)


def _mask_roi(mask: np.ndarray, fallback_bbox: list[int]) -> list[float]:
    ys, xs = np.nonzero(mask > 0)
    if len(xs) == 0:
        return [float(v) for v in fallback_bbox]
    return [float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)]


def _safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned or "mask"
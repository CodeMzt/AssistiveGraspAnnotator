"""Export pixel-level target maps (.npz) for RGB-Grasp-Tiny (Model B) training.

Generates per-object supervision maps:
  q_map          — per-pixel grasp quality        [0, 1]    float32  (H, W)
  sin2theta_map  — sin(2θ) orientation encoding   [-1, 1]   float32  (H, W)
  cos2theta_map  — cos(2θ) orientation encoding   [-1, 1]   float32  (H, W)
  width_map      — per-pixel grasp width           [0, …]    float32  (H, W)

Convention:  θ = angle of width axis (p0 → p1) measured from positive x-axis.
             width is in map pixels (not normalised by the map dimension by default).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageFilter

from assistive_grasp_annotator.tools.geometry import (
    extend_bbox,
    grasp_angle,
    grasp_width,
    rasterize_polygon,
)
from assistive_grasp_annotator.models.annotation import DIFFICULTY_MAP

if TYPE_CHECKING:
    from assistive_grasp_annotator.models.dataset import DatasetModel


def export_target_maps(
    dataset: DatasetModel,
    output_dir: str | Path,
    map_size: tuple[int, int] = (320, 240),
    gaussian_sigma: float = 3.0,
) -> tuple[int, int]:
    """
    Generate target maps for every graspable object that has at least one grasp.

    Returns (exported_count, error_count).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    map_w, map_h = map_size

    exported = 0
    errors = 0

    for img_path in dataset.image_paths:
        try:
            ann = dataset.load_annotation(img_path)
            if ann.image_size is None:
                continue

            img_w, img_h = ann.image_size

            try:
                source_image = Image.open(img_path).convert("RGB")
            except Exception:
                errors += 1
                continue

            image_key = dataset._make_image_key(img_path)
            stem = Path(image_key).stem

            for obj in ann.objects:
                if not obj.grasps:
                    continue

                bbox = obj.bbox_xyxy
                padded = extend_bbox(bbox, padding_ratio=0.2,
                                     clamp_width=img_w, clamp_height=img_h)

                # --- ROI crop and resize to target map size ---
                px1, py1, px2, py2 = [int(round(v)) for v in padded]
                roi_pil = source_image.crop((px1, py1, px2, py2))
                roi_np = np.array(roi_pil.resize((map_w, map_h), Image.Resampling.BILINEAR),
                                  dtype=np.uint8)

                # Scale factor: ROI-pixel → map-pixel
                roi_w, roi_h = px2 - px1, py2 - py1
                sx = map_w / roi_w if roi_w > 0 else 1.0
                sy = map_h / roi_h if roi_h > 0 else 1.0

                # --- Initialise empty maps ---
                q_map = np.zeros((map_h, map_w), dtype=np.float32)
                sin2theta_map = np.zeros((map_h, map_w), dtype=np.float32)
                cos2theta_map = np.zeros((map_h, map_w), dtype=np.float32)
                width_map = np.zeros((map_h, map_w), dtype=np.float32)
                quality_map = np.zeros((map_h, map_w), dtype=np.float32)  # for tie-breaking

                # --- Rasterise each grasp ---
                for grasp in obj.grasps:
                    # Transform grasp points: image → ROI → map
                    map_pts: list[tuple[float, float]] = []
                    for pt in grasp.points:
                        mx = (pt[0] - padded[0]) * sx
                        my = (pt[1] - padded[1]) * sy
                        map_pts.append((mx, my))

                    quality = DIFFICULTY_MAP.get(grasp.difficulty, 0.0)
                    if quality <= 0:
                        continue

                    theta = grasp_angle(map_pts)
                    sin2t = math.sin(2.0 * theta)
                    cos2t = math.cos(2.0 * theta)
                    g_width = grasp_width(map_pts)

                    pixels = rasterize_polygon(map_pts, map_h, map_w)

                    for row, col in pixels:
                        if quality > quality_map[row, col]:
                            quality_map[row, col] = quality
                            q_map[row, col] = quality
                            sin2theta_map[row, col] = sin2t
                            cos2theta_map[row, col] = cos2t
                            width_map[row, col] = g_width

                if quality_map.max() <= 0:
                    continue

                # --- Gaussian smooth Q_map ---
                q_img = Image.fromarray((q_map * 255).astype(np.uint8))
                q_img = q_img.filter(ImageFilter.GaussianBlur(radius=gaussian_sigma))
                q_map = np.array(q_img, dtype=np.float32) / 255.0
                q_map = np.clip(q_map, 0.0, 1.0)

                # --- Save ---
                img_out_dir = output_dir / stem
                img_out_dir.mkdir(parents=True, exist_ok=True)

                prefix = f"obj_{obj.instance_id:03d}"

                # ROI image
                roi_path = img_out_dir / f"{prefix}.png"
                Image.fromarray(roi_np).save(roi_path)

                # Target maps
                npz_path = img_out_dir / f"{prefix}.npz"
                np.savez_compressed(
                    npz_path,
                    q_map=q_map,
                    sin2theta_map=sin2theta_map,
                    cos2theta_map=cos2theta_map,
                    width_map=width_map,
                )

                # Metadata JSON
                meta = {
                    "source_image": str(img_path),
                    "source_bbox": bbox,
                    "padded_bbox": padded,
                    "map_size": [map_w, map_h],
                    "instance_id": obj.instance_id,
                    "class_id": obj.class_id,
                    "class_name": obj.class_name,
                    "graspable": obj.graspable,
                    "policy": obj.policy,
                    "grasps": [
                        {
                            "grasp_id": g.grasp_id,
                            "points_roi": [
                                [round((p[0] - padded[0]) * sx, 2),
                                 round((p[1] - padded[1]) * sy, 2)]
                                for p in g.points
                            ],
                            "quality": g.quality,
                            "difficulty": g.difficulty,
                            "note": g.note,
                        }
                        for g in obj.grasps
                    ],
                }
                with open(img_out_dir / f"{prefix}.json", "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2, ensure_ascii=False)

                exported += 1

        except Exception:
            errors += 1

    return (exported, errors)

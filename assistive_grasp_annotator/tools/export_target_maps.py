"""Export pixel-level target maps (.npz) for RGB-Grasp-Tiny (Model B) training.

References:
  GG-CNN (Morrison et al., RSS 2018) — pos/angle/width output heads,
  compact-polygon center-third encoding, sin(2θ)/cos(2θ) wrapping.

Output per graspable object:
  {image_stem}/obj_{instance_id:03d}.png   — letterboxed ROI (square)
  {image_stem}/obj_{instance_id:03d}.npz   — target maps
  {image_stem}/obj_{instance_id:03d}.json  — metadata

.npz keys:
  q_map          (S, S) float32  [0, 1]    per-pixel grasp quality
  sin2theta_map  (S, S) float32  [-1, 1]   sin(2θ) orientation
  cos2theta_map  (S, S) float32  [-1, 1]   cos(2θ) orientation
  width_map      (S, S) float32  [0, 1]    grasp width, normalised / map_size
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageFilter

from assistive_grasp_annotator.models.annotation import DIFFICULTY_MAP
from assistive_grasp_annotator.tools.geometry import (
    compute_compact_polygon,
    extend_bbox,
    grasp_angle,
    grasp_width,
    rasterize_polygon,
)

if TYPE_CHECKING:
    from assistive_grasp_annotator.models.dataset import DatasetModel


def export_target_maps(
    dataset: DatasetModel,
    output_dir: str | Path,
    map_size: int = 300,
    gaussian_sigma: float = 0.0,
) -> tuple[int, int]:
    """Generate target maps for every graspable object that has grasps.

    Parameters
    ----------
    dataset : DatasetModel
    output_dir : str or Path
    map_size : int
        Output square side length in pixels (default 300, matches GG-CNN).
    gaussian_sigma : float
        Stddev for optional Q-map blur.  0 = off (match GG-CNN binary fill).

    Returns
    -------
    (exported_count, error_count)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

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

                # ---- ROI crop ----
                px1, py1, px2, py2 = [int(round(v)) for v in padded]
                roi_w, roi_h = px2 - px1, py2 - py1
                if roi_w <= 0 or roi_h <= 0:
                    continue
                roi_pil = source_image.crop((px1, py1, px2, py2))

                # ---- letterbox-resize to (map_size × map_size) ----
                scale = map_size / max(roi_w, roi_h)
                scaled_w = int(round(roi_w * scale))
                scaled_h = int(round(roi_h * scale))
                roi_scaled = roi_pil.resize((scaled_w, scaled_h), Image.Resampling.BILINEAR)

                # centre on black canvas
                canvas = Image.new("RGB", (map_size, map_size), (0, 0, 0))
                ox = (map_size - scaled_w) // 2
                oy = (map_size - scaled_h) // 2
                canvas.paste(roi_scaled, (ox, oy))
                roi_np = np.array(canvas, dtype=np.uint8)

                # ---- transform grasp points: image → map coords ----
                def to_map(pt):
                    mx = (pt[0] - padded[0]) * scale + float(ox)
                    my = (pt[1] - padded[1]) * scale + float(oy)
                    return (mx, my)

                # ---- initialise empty maps ----
                q_map = np.zeros((map_size, map_size), dtype=np.float32)
                sin2theta_map = np.zeros((map_size, map_size), dtype=np.float32)
                cos2theta_map = np.zeros((map_size, map_size), dtype=np.float32)
                width_map = np.zeros((map_size, map_size), dtype=np.float32)
                tie_map = np.zeros((map_size, map_size), dtype=np.float32)   # quality tie-breaker

                # ---- rasterise each grasp ----
                for grasp in obj.grasps:
                    quality = DIFFICULTY_MAP.get(grasp.difficulty, 0.0)
                    if quality <= 0:
                        continue

                    # full grasp points in map coords
                    full_map_pts = [to_map(p) for p in grasp.points]

                    # compact polygon (centre 1/3)
                    compact_pts = compute_compact_polygon(full_map_pts, factor=1.0 / 3.0)

                    theta = grasp_angle(full_map_pts)
                    sin2t = math.sin(2.0 * theta)
                    cos2t = math.cos(2.0 * theta)
                    w_norm = grasp_width(full_map_pts) / map_size

                    pixels = rasterize_polygon(compact_pts, map_size, map_size)

                    for row, col in pixels:
                        if quality > tie_map[row, col]:
                            tie_map[row, col] = quality
                            q_map[row, col] = quality
                            sin2theta_map[row, col] = sin2t
                            cos2theta_map[row, col] = cos2t
                            width_map[row, col] = w_norm

                if tie_map.max() <= 0:
                    continue

                # ---- optional Gaussian smooth of Q_map ----
                if gaussian_sigma > 0:
                    q_img = Image.fromarray((q_map * 255).astype(np.uint8))
                    q_img = q_img.filter(ImageFilter.GaussianBlur(radius=gaussian_sigma))
                    q_map = np.array(q_img, dtype=np.float32) / 255.0
                    q_map = np.clip(q_map, 0.0, 1.0)

                # ---- save ----
                img_out_dir = output_dir / stem
                img_out_dir.mkdir(parents=True, exist_ok=True)

                prefix = f"obj_{obj.instance_id:03d}"

                # ROI image (letterboxed)
                Image.fromarray(roi_np).save(img_out_dir / f"{prefix}.png")

                # target maps
                np.savez_compressed(
                    img_out_dir / f"{prefix}.npz",
                    q_map=q_map,
                    sin2theta_map=sin2theta_map,
                    cos2theta_map=cos2theta_map,
                    width_map=width_map,
                )

                # metadata
                meta = {
                    "source_image": str(img_path),
                    "source_bbox": bbox,
                    "padded_bbox": padded,
                    "map_size": map_size,
                    "letterbox_offset": [ox, oy],
                    "scale": round(scale, 6),
                    "instance_id": obj.instance_id,
                    "class_id": obj.class_id,
                    "class_name": obj.class_name,
                    "graspable": obj.graspable,
                    "policy": obj.policy,
                    "grasps": [
                        {
                            "grasp_id": g.grasp_id,
                            "points_map": [
                                [round(to_map(p)[0], 2), round(to_map(p)[1], 2)]
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

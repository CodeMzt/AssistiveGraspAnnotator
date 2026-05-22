"""Export grasp ROI images and JSON for graspable objects."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PIL import Image

from assistive_grasp_annotator.tools.geometry import extend_bbox, transform_to_roi

if TYPE_CHECKING:
    from assistive_grasp_annotator.models.dataset import DatasetModel


def export_grasp_rois(
    dataset: DatasetModel,
    output_dir: str | Path,
) -> tuple[int, int]:
    """
    For each annotation with grasps: pad bbox 20%, crop ROI image,
    transform grasp points to ROI-local, save image + JSON.
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

            # Open source image
            try:
                image = Image.open(img_path).convert("RGB")
            except Exception:
                errors += 1
                continue

            img_w, img_h = ann.image_size
            image_key = dataset._make_image_key(img_path)
            stem = Path(image_key).stem

            for obj in ann.objects:
                if not obj.grasps:
                    continue

                bbox = obj.bbox_xyxy
                padded = extend_bbox(bbox, padding_ratio=0.2,
                                     clamp_width=img_w, clamp_height=img_h)
                px1, py1, px2, py2 = [int(round(v)) for v in padded]

                # Crop ROI
                roi = image.crop((px1, py1, px2, py2))

                # Transform grasp points
                roi_grasps = []
                for grasp in obj.grasps:
                    flat = [(p[0], p[1]) for p in grasp.points]
                    local = transform_to_roi(flat, padded)
                    roi_grasps.append({
                        "grasp_id": grasp.grasp_id,
                        "points_roi": [[round(p[0], 2), round(p[1], 2)] for p in local],
                        "axis_convention": grasp.axis_convention,
                        "quality": grasp.quality,
                        "difficulty": grasp.difficulty,
                        "note": grasp.note,
                    })

                roi_data = {
                    "source_image": str(img_path),
                    "source_bbox": bbox,
                    "padded_bbox": padded,
                    "instance_id": obj.instance_id,
                    "class_id": obj.class_id,
                    "class_name": obj.class_name,
                    "graspable": obj.graspable,
                    "policy": obj.policy,
                    "grasps": roi_grasps,
                }

                # Create subfolder per image
                img_out_dir = output_dir / stem
                img_out_dir.mkdir(parents=True, exist_ok=True)

                # Save ROI image
                roi_filename = f"obj_{obj.instance_id:03d}.png"
                roi.save(img_out_dir / roi_filename)

                # Save ROI JSON
                json_filename = f"obj_{obj.instance_id:03d}.json"
                with open(img_out_dir / json_filename, "w", encoding="utf-8") as f:
                    json.dump(roi_data, f, indent=2, ensure_ascii=False)

                exported += 1

        except Exception:
            errors += 1

    return (exported, errors)

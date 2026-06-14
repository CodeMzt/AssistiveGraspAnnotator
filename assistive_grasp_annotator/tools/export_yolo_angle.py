"""Export YOLO-Angle custom labels from annotations.

Output format per line:
    class_id cx cy w h sin2theta cos2theta yaw_valid angle_mask

Where:
    - cx, cy, w, h : YOLO normalized bbox (same as detection export)
    - sin2theta, cos2theta : sin(2*theta) / cos(2*theta) from main_axis_points
    - yaw_valid : 1 if yaw_label_status == "valid", else 0
    - angle_mask : 1 to include in angle loss (only when yaw_label_status == "valid"
                   AND main_axis_points exist), else 0
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

from assistive_grasp_annotator.tools.geometry import (
    axis_angle,
    normalize_bbox,
)

if TYPE_CHECKING:
    from assistive_grasp_annotator.models.dataset import DatasetModel


def export_yolo_angle_labels(
    dataset: DatasetModel,
    output_dir: str | Path,
) -> tuple[int, int]:
    """Export YOLO-Angle format labels (detection + angle head).

    One .txt file per image. Each line:
        class_id cx cy w h sin2theta cos2theta yaw_valid angle_mask
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    exported = 0
    errors = 0

    for img_path in dataset.image_paths:
        try:
            ann = dataset.load_annotation(img_path)
            if ann.image_size is None or not ann.objects:
                continue
            img_w, img_h = ann.image_size

            image_key = dataset._make_image_key(img_path)
            out_path = output_dir / Path(image_key).with_suffix(".txt")
            out_path.parent.mkdir(parents=True, exist_ok=True)

            lines = []
            for obj in ann.objects:
                bbox = obj.bbox_xyxy
                cx, cy, bw, bh = normalize_bbox(bbox, img_w, img_h)

                yaw_valid = 1 if obj.yaw_label_status == "valid" else 0

                has_valid_axis = (
                    obj.yaw_label_status == "valid"
                    and obj.has_axis
                    and obj.main_axis_points is not None
                )

                if has_valid_axis:
                    theta = axis_angle(obj.main_axis_points)
                    sin2t = math.sin(2.0 * theta)
                    cos2t = math.cos(2.0 * theta)
                    angle_mask = 1
                else:
                    sin2t = 0.0
                    cos2t = 0.0
                    angle_mask = 0

                lines.append(
                    f"{obj.class_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f} "
                    f"{sin2t:.6f} {cos2t:.6f} {yaw_valid} {angle_mask}"
                )

            with open(out_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + ("\n" if lines else ""))

            exported += 1
        except Exception:
            errors += 1

    return (exported, errors)

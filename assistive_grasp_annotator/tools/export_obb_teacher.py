"""Export optional OBB teacher labels from annotations.

Output format per line (YOLO-OBB style):
    class_id x1 y1 x2 y2 x3 y3 x4 y4

All coordinates normalized to [0, 1] relative to image width/height.

Only objects with obb_points are exported.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from assistive_grasp_annotator.models.dataset import DatasetModel


def export_obb_teacher_labels(
    dataset: DatasetModel,
    output_dir: str | Path,
) -> tuple[int, int]:
    """Export OBB teacher labels for objects that have obb_points.

    One .txt file per image. Each line:
        class_id x1_norm y1_norm x2_norm y2_norm x3_norm y3_norm x4_norm y4_norm
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
                if not obj.has_obb or obj.obb_points is None:
                    continue

                # Normalize all 4 OBB points
                norm_pts = []
                for p in obj.obb_points:
                    norm_pts.append(f"{p[0] / img_w:.6f} {p[1] / img_h:.6f}")

                lines.append(f"{obj.class_id} {' '.join(norm_pts)}")

            with open(out_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + ("\n" if lines else ""))

            exported += 1
        except Exception:
            errors += 1

    return (exported, errors)

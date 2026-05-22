"""Export YOLO detection labels from annotations."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, TYPE_CHECKING

from assistive_grasp_annotator.tools.geometry import normalize_bbox

if TYPE_CHECKING:
    from assistive_grasp_annotator.models.dataset import DatasetModel


def export_yolo_labels(
    dataset: DatasetModel,
    output_dir: str | Path,
) -> tuple[int, int]:
    """
    For each annotation in the dataset, export a YOLO-format .txt file.

    Output preserves subdirectory structure relative to the images/ root.
    Each .txt line: class_id cx_norm cy_norm w_norm h_norm
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

            # Determine output path preserving camera subdirectory
            image_key = dataset._make_image_key(img_path)
            out_path = output_dir / Path(image_key).with_suffix(".txt")
            out_path.parent.mkdir(parents=True, exist_ok=True)

            lines = []
            for obj in ann.objects:
                bbox = obj.bbox_xyxy
                cx, cy, bw, bh = normalize_bbox(bbox, img_w, img_h)
                lines.append(f"{obj.class_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")

            with open(out_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + ("\n" if lines else ""))

            exported += 1
        except Exception:
            errors += 1

    return (exported, errors)

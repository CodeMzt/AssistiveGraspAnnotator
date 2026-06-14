"""One-shot migration from v1 (grasp-rectangle) annotations to v2 (YOLO-Angle).

Mapping table for class_id:
    v1      v2
    0 phone_A       → 4 phone_A
    1 remote_A      → 3 remote_A
    2 medicine_box_A → 0 medicine_box_A
    3 tissue_box_A   → 2 tissue_pack_A
    4 cup_A          → 5 cup_other
    5 bottle_A       → 1 bottle_A
    6 cup_other      → 5 cup_other
    7 phone_other    → 9 unknown_object
    8 bottle_other   → 6 bottle_other
    9 book           → 8 book
    10 box_other     → 7 box_other

Usage:
    python -m assistive_grasp_annotator.tools.migrate_v1_to_v2 <dataset_root>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CLASS_ID_MAP: dict[int, int] = {
    0: 4,   # phone_A → phone_A
    1: 3,   # remote_A → remote_A
    2: 0,   # medicine_box_A → medicine_box_A
    3: 2,   # tissue_box_A → tissue_pack_A
    4: 5,   # cup_A → cup_other
    5: 1,   # bottle_A → bottle_A
    6: 5,   # cup_other → cup_other
    7: 9,   # phone_other → unknown_object
    8: 6,   # bottle_other → bottle_other
    9: 8,   # book → book
    10: 7,  # box_other → box_other
}

CLASS_NAME_MAP: dict[str, str] = {
    "tissue_box_A": "tissue_pack_A",
    "cup_A": "cup_other",
    "phone_other": "unknown_object",
}


def is_v2_format(data: dict) -> bool:
    """Detect whether the annotation is already in v2 format."""
    for obj in data.get("objects", []):
        if "yaw_label_status" in obj:
            return True
    return False


def object_difficulty_from_grasps(grasps: list[dict]) -> str:
    """Derive object-level difficulty from grasp-level difficulties."""
    if not grasps:
        return "easy"
    priority = {"hard": 3, "medium": 2, "easy": 1, "invalid": 0}
    worst = "easy"
    worst_p = 0
    for g in grasps:
        d = g.get("difficulty", "easy")
        if priority.get(d, 0) > worst_p:
            worst = d
            worst_p = priority[d]
    return worst


def v1_bbox_from_grasps(grasps: list[dict]) -> list[float] | None:
    """Compute an approximate bbox from grasp points."""
    all_points = []
    for g in grasps:
        for p in g.get("points", []):
            all_points.append((p[0], p[1]))
    if not all_points:
        return None
    xs = [p[0] for p in all_points]
    ys = [p[1] for p in all_points]
    return [min(xs), min(ys), max(xs), max(ys)]


def migrate_object(obj: dict) -> dict:
    """Convert a single v1 object dict to v2 format."""
    old_class_id = obj.get("class_id", 0)
    old_class_name = obj.get("class_name", "")
    new_class_id = CLASS_ID_MAP.get(old_class_id, old_class_id)
    new_class_name = CLASS_NAME_MAP.get(old_class_name, old_class_name)

    old_grasps = obj.get("grasps", [])
    graspable = obj.get("graspable", True)

    # Determine yaw_label_status from grasp presence and class
    if old_grasps:
        # Had grasps annotated → likely had orientation info
        yaw_label_status = "valid"
    elif not graspable:
        yaw_label_status = "optional"
    else:
        yaw_label_status = "optional"

    # Extract main_axis_points from first grasp if available
    main_axis_points = None
    if old_grasps:
        g0 = old_grasps[0]
        pts = g0.get("points", [])
        if len(pts) >= 2:
            # p0→p1 was the grasp width axis (old convention)
            main_axis_points = [pts[0][:2], pts[1][:2]]

    # Extract obb_points from first grasp if it has 4 points
    obb_points = None
    if old_grasps:
        g0 = old_grasps[0]
        pts = g0.get("points", [])
        if len(pts) == 4:
            obb_points = [p[:2] for p in pts]

    difficulty = object_difficulty_from_grasps(old_grasps)

    # Determine occlusion level from old data (default 0)
    occlusion_level = obj.get("occlusion_level", 0)

    new_obj = {
        "instance_id": obj.get("instance_id", 1),
        "class_id": new_class_id,
        "class_name": new_class_name,
        "bbox_xyxy": obj.get("bbox_xyxy", [0, 0, 0, 0]),
        "graspable": graspable,
        "template_id": new_class_name if graspable else "none",
        "yaw_label_status": yaw_label_status,
        "occlusion_level": occlusion_level,
        "difficulty": difficulty,
        "notes": obj.get("notes", f"[migrated from v1, class was {old_class_name}]"),
    }
    if main_axis_points:
        new_obj["main_axis_points"] = main_axis_points
    if obb_points:
        new_obj["obb_points"] = obb_points
    return new_obj


def migrate_file(filepath: Path, dry_run: bool = False) -> bool:
    """Migrate a single annotation JSON file from v1 to v2."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if is_v2_format(data):
        print(f"  [SKIP] already v2: {filepath.name}")
        return False

    new_objects = [migrate_object(obj) for obj in data.get("objects", [])]

    data["objects"] = new_objects
    # Remove v1-only fields if present
    data.pop("policy", None)

    if not dry_run:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"  [OK] migrated: {filepath.name} ({len(new_objects)} objects)")
    return True


def migrate_dataset(root: str | Path, dry_run: bool = False):
    """Migrate all annotation JSON files in a dataset directory."""
    root = Path(root)
    ann_dir = root / "annotations"
    if not ann_dir.is_dir():
        print(f"ERROR: annotations directory not found: {ann_dir}")
        return

    json_files = sorted(ann_dir.rglob("*.json"))
    if not json_files:
        print(f"No JSON files found in {ann_dir}")
        return

    print(f"Found {len(json_files)} annotation files.")
    if dry_run:
        print("[DRY RUN — no files will be modified]")

    migrated = 0
    skipped = 0
    for fp in json_files:
        try:
            if migrate_file(fp, dry_run=dry_run):
                migrated += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"  [ERROR] {fp.name}: {e}")

    print(f"\nDone. Migrated: {migrated}, Skipped: {skipped} (already v2)")


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m assistive_grasp_annotator.tools.migrate_v1_to_v2 <dataset_root> [--dry-run]")
        sys.exit(1)

    dataset_root = sys.argv[1]
    dry_run = "--dry-run" in sys.argv
    migrate_dataset(dataset_root, dry_run=dry_run)


if __name__ == "__main__":
    main()

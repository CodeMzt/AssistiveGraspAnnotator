"""Canonicalize AssistiveGrasp new_dataset annotations in place.

The command defaults to dry-run. Use --apply only after reviewing the report.
It snapshots annotations/classes before any write, then rewrites JSON files
atomically and emits a migration report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


CANONICAL_BY_ID = {
    0: "earbud",
    1: "phial",
    2: "bottle",
    3: "phone",
    4: "remote",
    5: "tissue",
    6: "apple",
}
LEGACY_CLASS_SUFFIX = "_" + "A"
YAW_SENSITIVE = {"earbud", "phone", "remote", "tissue"}
YAW_FREE = {"phial", "bottle", "apple"}


def migrate_dataset(root: Path, apply: bool = False) -> dict[str, Any]:
    root = root.resolve()
    annotations_dir = root / "annotations"
    if not annotations_dir.is_dir():
        raise ValueError(f"annotations directory not found: {annotations_dir}")
    report_dir = root / "state" / "migrations" / datetime.now().strftime("%Y%m%d_%H%M%S_new_dataset_canonicalize")
    annotation_paths = sorted(annotations_dir.rglob("*.json"))
    report: dict[str, Any] = {
        "schema_version": "new_dataset_canonicalize_v1",
        "root": str(root),
        "apply": apply,
        "report_dir": str(report_dir),
        "annotation_files": len(annotation_paths),
        "changed_files": 0,
        "object_count": 0,
        "legacy_class_name_count": 0,
        "class_name_changes": 0,
        "yaw_status_changes": 0,
        "bbox_changes": 0,
        "axis_changes": 0,
        "yaw_review_queue": [],
        "unknown_class_ids": [],
        "files": [],
    }
    if apply:
        _snapshot(root, report_dir, annotation_paths)
    for ann_path in annotation_paths:
        original_text = ann_path.read_text(encoding="utf-8")
        data = json.loads(original_text)
        before_digest = _sha256_bytes(original_text.encode("utf-8"))
        changed = False
        file_report = {
            "path": str(ann_path.relative_to(root)),
            "object_count": 0,
            "class_name_changes": 0,
            "legacy_class_name_count": 0,
            "yaw_status_changes": 0,
            "yaw_review": [],
        }
        for obj in data.get("objects", []):
            file_report["object_count"] += 1
            report["object_count"] += 1
            class_id = _safe_int(obj.get("class_id"))
            canonical = CANONICAL_BY_ID.get(class_id)
            if canonical is None:
                report["unknown_class_ids"].append({"path": file_report["path"], "instance_id": obj.get("instance_id"), "class_id": obj.get("class_id")})
                continue

            old_name = str(obj.get("class_name") or "")
            if old_name.endswith(LEGACY_CLASS_SUFFIX):
                file_report["legacy_class_name_count"] += 1
                report["legacy_class_name_count"] += 1
            if old_name != canonical:
                obj["class_name"] = canonical
                file_report["class_name_changes"] += 1
                report["class_name_changes"] += 1
                changed = True

            old_yaw = str(obj.get("yaw_label_status") or "optional")
            next_yaw = old_yaw
            has_axis = _has_axis(obj)
            if canonical in YAW_SENSITIVE:
                if has_axis and old_yaw != "valid":
                    next_yaw = "valid"
                elif not has_axis and old_yaw == "valid":
                    next_yaw = "optional"
                if not has_axis:
                    item = {"path": file_report["path"], "instance_id": obj.get("instance_id"), "class_name": canonical}
                    file_report["yaw_review"].append(item)
                    report["yaw_review_queue"].append(item)
            elif canonical in YAW_FREE:
                next_yaw = "not_required"

            if next_yaw != old_yaw:
                obj["yaw_label_status"] = next_yaw
                file_report["yaw_status_changes"] += 1
                report["yaw_status_changes"] += 1
                changed = True

        next_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        after_digest = _sha256_bytes(next_text.encode("utf-8"))
        file_report["changed"] = changed
        file_report["before_sha256"] = before_digest
        file_report["after_sha256"] = after_digest
        if changed:
            report["changed_files"] += 1
            if apply:
                _atomic_write_text(ann_path, next_text)
        if changed or file_report["yaw_review"]:
            report["files"].append(file_report)
    if apply:
        _write_classes_yaml(root / "classes.yaml")
    report_path = report_dir / ("migration_report.json" if apply else "migration_report_dry_run.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def _snapshot(root: Path, report_dir: Path, annotation_paths: list[Path]) -> None:
    snapshot_root = report_dir / "snapshot"
    snapshot_ann = snapshot_root / "annotations"
    snapshot_ann.mkdir(parents=True, exist_ok=True)
    manifest = []
    for path in annotation_paths:
        rel = path.relative_to(root / "annotations")
        dst = snapshot_ann / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)
        manifest.append({"path": str(path.relative_to(root)), "sha256": _sha256_file(path), "bytes": path.stat().st_size})
    classes_path = root / "classes.yaml"
    if classes_path.exists():
        shutil.copy2(classes_path, snapshot_root / "classes.yaml")
        manifest.append({"path": "classes.yaml", "sha256": _sha256_file(classes_path), "bytes": classes_path.stat().st_size})
    (report_dir / "snapshot_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_classes_yaml(path: Path) -> None:
    classes = [{"id": class_id, "name": name, "graspable": True} for class_id, name in CANONICAL_BY_ID.items()]
    text = yaml.safe_dump({"classes": classes}, allow_unicode=True, sort_keys=False)
    _atomic_write_text(path, text)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=str(path.parent), newline="\n") as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _has_axis(obj: dict[str, Any]) -> bool:
    points = obj.get("main_axis_points")
    return isinstance(points, list) and len(points) == 2 and all(isinstance(p, list) and len(p) == 2 for p in points)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = migrate_dataset(args.dataset_root, apply=args.apply)
    print(json.dumps({
        "apply": report["apply"],
        "report_dir": report["report_dir"],
        "annotation_files": report["annotation_files"],
        "changed_files": report["changed_files"],
        "object_count": report["object_count"],
        "legacy_class_name_count": report["legacy_class_name_count"],
        "class_name_changes": report["class_name_changes"],
        "yaw_status_changes": report["yaw_status_changes"],
        "yaw_review_queue": len(report["yaw_review_queue"]),
        "unknown_class_ids": len(report["unknown_class_ids"]),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

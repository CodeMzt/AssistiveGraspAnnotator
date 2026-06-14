"""Read-only audit for legacy annotation JSON files."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from assistive_grasp_annotator.models.annotation import AnnotationModel
from assistive_grasp_annotator.models.classes import ClassRegistry
from assistive_grasp_annotator.tools.validators import validate_annotation


def _load_class_registry(dataset_root: Path) -> ClassRegistry | None:
    classes_yaml = dataset_root / "classes.yaml"
    if not classes_yaml.exists():
        return None
    return ClassRegistry.from_yaml(classes_yaml)


def audit_annotations(dataset_root: Path) -> dict[str, Any]:
    """Scan annotations without modifying files."""
    annotations_root = dataset_root / "annotations"
    registry = _load_class_registry(dataset_root)
    issues: list[dict[str, Any]] = []
    annotation_count = 0

    for path in sorted(annotations_root.rglob("*.json")):
        annotation_count += 1
        image_key = str(path.relative_to(annotations_root).with_suffix("")).replace("\\", "/")
        try:
            annotation = AnnotationModel.load(path)
            for issue in validate_annotation(annotation, registry):
                issues.append(issue.to_dict(image_key=image_key))
        except Exception as exc:  # pragma: no cover - defensive audit output
            issues.append(
                {
                    "severity": "error",
                    "code": "annotation_load_error",
                    "image_key": image_key,
                    "message": f"标注文件读取失败：{exc}",
                    "suggestion": "检查 JSON 格式，必要时从备份恢复该标注文件。",
                }
            )

    error_count = sum(1 for item in issues if item.get("severity") == "error")
    warning_count = sum(1 for item in issues if item.get("severity") == "warning")
    return {
        "dataset_root": str(dataset_root),
        "annotation_count": annotation_count,
        "error_count": error_count,
        "warning_count": warning_count,
        "issues": issues,
    }


def write_csv(report: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["severity", "code", "image_key", "instance_id", "message", "suggestion"]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for issue in report["issues"]:
            writer.writerow({field: issue.get(field, "") for field in fields})


def write_json(report: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit legacy AssistiveGraspAnnotator annotations without modifying data.")
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument("--out-csv", type=Path, default=None)
    parser.add_argument("--strict-exit", action="store_true", help="Return exit code 1 when hard errors are found.")
    args = parser.parse_args(argv)

    report = audit_annotations(args.dataset_root)
    if args.out_json:
        write_json(report, args.out_json)
    if args.out_csv:
        write_csv(report, args.out_csv)

    print(
        f"Audited {report['annotation_count']} annotation file(s): "
        f"{report['error_count']} error(s), {report['warning_count']} warning(s)."
    )
    if not args.out_json and not args.out_csv and report["issues"]:
        print(json.dumps(report["issues"][:50], ensure_ascii=False, indent=2))

    return 1 if args.strict_exit and report["error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

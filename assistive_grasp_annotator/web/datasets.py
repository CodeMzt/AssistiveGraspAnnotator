"""Dataset filesystem service used by the FastAPI app."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from PIL import Image

from assistive_grasp_annotator.models.annotation import AnnotationModel
from assistive_grasp_annotator.models.classes import ClassRegistry
from assistive_grasp_annotator.tools.annotation_quality import ValidationIssue
from assistive_grasp_annotator.tools.mask_common import is_supported_mask_candidate, object_signature
from assistive_grasp_annotator.tools.sam_teacher_client import SamTeacherError, generate_sam_mask_candidate
from assistive_grasp_annotator.tools.validators import validate_annotation
from assistive_grasp_annotator.web.config import WebConfig, resolve_allowed_path
from assistive_grasp_annotator.web.ids import decode_image_id, encode_image_id
from assistive_grasp_annotator.web.state import StateStore
from assistive_grasp_annotator.web.uploads import AssembledUpload


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
IGNORED_SCAN_DIRS = {"annotations", "generated", "splits", ".aga_trash"}
YAW_SENSITIVE_CLASSES = {"earbud", "phone", "remote", "tissue"}
CANONICAL_CLASS_NAMES = {"earbud", "phial", "bottle", "phone", "remote", "tissue", "apple"}
LEGACY_CLASS_SUFFIX = "_" + "A"


class DatasetError(ValueError):
    pass


class MaskGenerationError(DatasetError):
    pass


class DatasetValidationError(DatasetError):
    def __init__(self, validation: dict[str, list[dict[str, Any]]]):
        super().__init__("Annotation validation failed")
        self.validation = validation


def split_validation_messages(
    messages: list[ValidationIssue | str],
    image_key: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, ValidationIssue):
            payload = message.to_dict(image_key=image_key)
            if message.severity == "warning":
                warnings.append(payload)
            else:
                errors.append(payload)
            continue
        payload = {"severity": "warning" if "WARNING" in message else "error", "message": message}
        if image_key is not None:
            payload["image_key"] = image_key
        if payload["severity"] == "warning":
            payload["message"] = message.replace(" (WARNING)", "").replace("WARNING: ", "")
            warnings.append(payload)
        else:
            errors.append(payload)
    return {"errors": errors, "warnings": warnings}


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._")
    return cleaned or "dataset"


def _annotation_etag(path: Path) -> str:
    if not path.exists():
        return "missing"
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _describe_numbers(values: list[float]) -> dict[str, float | int | None]:
    clean = sorted(float(v) for v in values if v == v)
    if not clean:
        return {"count": 0, "mean": None, "p10": None, "p50": None, "p90": None}
    return {
        "count": len(clean),
        "mean": sum(clean) / len(clean),
        "p10": _percentile(clean, 0.10),
        "p50": _percentile(clean, 0.50),
        "p90": _percentile(clean, 0.90),
    }


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    index = int(round((len(sorted_values) - 1) * q))
    index = max(0, min(len(sorted_values) - 1, index))
    return sorted_values[index]


def _class_suggestions(row: dict[str, Any]) -> list[str]:
    suggestions: list[str] = []
    object_count = int(row["object_count"])
    axis_count = int(row.get("axis_count", 0))
    yaw_valid_count = int(row.get("yaw_valid_count", 0))
    if object_count < 50:
        suggestions.append("类别样本偏少，建议优先追加采集。")
    if object_count > 0 and yaw_valid_count == 0 and row.get("graspable"):
        suggestions.append("可抓取类别缺少有效主轴标注 (yaw_label_status=valid)，请切换到 Axis 模式补标。")
    if object_count > 0 and axis_count < object_count * 0.5 and row.get("graspable"):
        suggestions.append("主轴标注覆盖率不足 50%，建议补标主要姿态方向。")
    return suggestions


def _class_suggestions_v2(row: dict[str, Any]) -> list[str]:
    suggestions: list[str] = []
    object_count = int(row["object_count"])
    axis_count = int(row.get("axis_count", 0))
    yaw_valid_count = int(row.get("yaw_valid_count", 0))
    if object_count == 0:
        suggestions.append("该类别尚无标注，如果是训练类别需要优先采集。")
    elif object_count < 50:
        suggestions.append("类别样本偏少，建议优先追加采集。")
    if object_count > 0 and yaw_valid_count == 0 and row.get("graspable"):
        suggestions.append("可抓取类别缺少有效主轴标注 (yaw_label_status=valid)，请切换到 Axis 模式补标。")
    if object_count > 0 and axis_count < object_count * 0.5 and row.get("graspable"):
        suggestions.append("主轴标注覆盖率不足 50%，建议补标主要姿态方向。")
    return suggestions


def _normalize_classes(classes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    seen_names: set[str] = set()
    for raw in classes:
        try:
            class_id = int(raw.get("id"))
        except (TypeError, ValueError) as exc:
            raise DatasetError("Class id must be an integer.") from exc
        if class_id < 0:
            raise DatasetError("Class id must be non-negative.")
        if class_id in seen_ids:
            raise DatasetError(f"Duplicate class id: {class_id}")
        name = str(raw.get("name", "")).strip()
        if not name:
            raise DatasetError("Class name is required.")
        if name.endswith(LEGACY_CLASS_SUFFIX) or name not in CANONICAL_CLASS_NAMES:
            raise DatasetError("Class name must be one of canonical object_vocab_v1 names: earbud, phial, bottle, phone, remote, tissue, apple.")
        if name in seen_names:
            raise DatasetError(f"Duplicate class name: {name}")
        normalized.append(
            {
                "id": class_id,
                "name": name,
                "graspable": bool(raw.get("graspable", True)),
            }
        )
        seen_ids.add(class_id)
        seen_names.add(name)
    return sorted(normalized, key=lambda item: item["id"])


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 10000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise DatasetError(f"Could not allocate unique trash path for {path.name}")


def _create_standard_dataset_dirs(root: Path, camera: str = "camera_1") -> None:
    (root / "images" / camera).mkdir(parents=True, exist_ok=True)
    (root / "annotations").mkdir(parents=True, exist_ok=True)
    (root / "splits").mkdir(parents=True, exist_ok=True)
    (root / "generated").mkdir(parents=True, exist_ok=True)


def _looks_like_dataset_root(path: Path) -> bool:
    return (
        (path / "images").is_dir()
        or (path / "classes.yaml").is_file()
        or (path / "annotations").is_dir()
    )


def _count_annotation(ann_path: Path) -> tuple[int, int]:
    """Fast count of objects and axis-annotated objects from annotation JSON."""
    try:
        data = json.loads(ann_path.read_text(encoding="utf-8"))
        objects = data.get("objects", [])
        object_count = len(objects)
        axis_count = sum(1 for obj in objects if obj.get("main_axis_points"))
        return object_count, axis_count
    except Exception:
        return 0, 0


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=str(path.parent)) as tmp:
        json.dump(payload, tmp, indent=2, ensure_ascii=False)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _review_status_from_score(score: int) -> str:
    if score >= 3:
        return "accepted"
    if score == 2:
        return "usable"
    if score == 1:
        return "uncertain"
    return "rejected"


@dataclass(frozen=True)
class ImageEntry:
    image_id: str
    image_key: str
    path: Path
    annotation_path: Path
    status: str
    object_count: int
    axis_count: int

    def to_dict(self, lock: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "image_key": self.image_key,
            "status": self.status,
            "object_count": self.object_count,
            "axis_count": self.axis_count,
            "lock": lock,
        }


class WebDataset:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.images_dir = self.root / "images" if (self.root / "images").is_dir() else self.root
        self.annotations_dir = self.root / "annotations"
        self.classes_path = self.root / "classes.yaml"
        self.annotations_dir.mkdir(parents=True, exist_ok=True)
        self._image_paths = self._scan_images()
        self._image_by_key = {self._make_image_key(path): path for path in self._image_paths}
        self._classes = self._load_classes()
        self._annotation_meta: dict[str, tuple[int, int]] = {}
        self._build_annotation_index()

    @property
    def image_paths(self) -> list[Path]:
        return self._image_paths

    @property
    def class_registry(self) -> ClassRegistry | None:
        return self._classes

    def _load_classes(self) -> ClassRegistry | None:
        if not self.classes_path.exists():
            return None
        try:
            return ClassRegistry.from_yaml(self.classes_path)
        except Exception:
            return None

    def _scan_images(self) -> list[Path]:
        images: list[Path] = []
        for path in self.images_dir.rglob("*"):
            rel_parts = set()
            try:
                rel_parts = set(path.relative_to(self.root).parts)
            except ValueError:
                pass
            if any(part.startswith(".") or part in IGNORED_SCAN_DIRS for part in rel_parts):
                continue
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                images.append(path.resolve())
        return sorted(set(images))

    def _refresh_images(self) -> None:
        self._image_paths = self._scan_images()
        self._image_by_key = {self._make_image_key(path): path for path in self._image_paths}
        self._build_annotation_index()

    def _build_annotation_index(self) -> None:
        self._annotation_meta = {}
        for path in self._image_paths:
            ann_path = self._get_annotation_path(path)
            if ann_path.exists():
                key = self._make_image_key(path)
                obj_count, axis_count = _count_annotation(ann_path)
                self._annotation_meta[key] = (obj_count, axis_count)

    def _update_annotation_meta(self, image_key: str) -> None:
        img_path = self._image_by_key.get(image_key)
        if img_path is None:
            return
        ann_path = self._get_annotation_path(img_path)
        if ann_path.exists():
            self._annotation_meta[image_key] = _count_annotation(ann_path)
        else:
            self._annotation_meta.pop(image_key, None)

    def _make_image_key(self, img_path: Path) -> str:
        images_dir = self.root / "images"
        try:
            return str(img_path.relative_to(images_dir))
        except ValueError:
            pass
        try:
            return str(img_path.relative_to(self.root))
        except ValueError:
            return img_path.name

    def _get_annotation_path(self, img_path: Path) -> Path:
        scan_root = self.images_dir if self.images_dir.is_dir() else self.root
        try:
            rel = img_path.relative_to(scan_root)
            return self.annotations_dir / rel.with_suffix(".json")
        except ValueError:
            return self.annotations_dir / f"{img_path.stem}.json"

    def image_path_for_id(self, image_id: str) -> Path:
        image_key = decode_image_id(image_id)
        path = self._image_by_key.get(image_key)
        if path is None:
            raise DatasetError(f"Unknown image id: {image_id}")
        return path

    def load_annotation(self, img_path: Path) -> AnnotationModel:
        ann_path = self._get_annotation_path(img_path)
        if ann_path.exists():
            try:
                ann = AnnotationModel.load(ann_path)
                ann.image_path = img_path
                return ann
            except Exception:
                pass

        ann = AnnotationModel(image_path=img_path)
        try:
            with Image.open(img_path) as im:
                ann.image_size = im.size
        except Exception:
            ann.image_size = (640, 480)
        ann.camera = img_path.parent.name if img_path.parent else ""
        return ann

    def annotation_payload(self, image_id: str) -> dict[str, Any]:
        img_path = self.image_path_for_id(image_id)
        ann_path = self._get_annotation_path(img_path)
        ann = self.load_annotation(img_path)
        return {
            "annotation": ann.to_dict(),
            "etag": _annotation_etag(ann_path),
            "image_id": image_id,
            "image_key": self._make_image_key(img_path),
        }

    def _mask_artifact_root(self, image_id: str, instance_id: int, kind: str) -> Path:
        img_path = self.image_path_for_id(image_id)
        image_key = self._make_image_key(img_path)
        rel = Path(image_key).with_suffix("")
        return self.root / "generated" / kind / rel / f"obj_{int(instance_id):03d}"

    def _latest_candidate_path(self, image_id: str, instance_id: int) -> Path | None:
        root = self._mask_artifact_root(image_id, instance_id, "mask_candidates")
        candidates = sorted(root.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in candidates:
            candidate = _read_json(path)
            if is_supported_mask_candidate(candidate):
                return path
        return None

    def _review_path(self, image_id: str, instance_id: int) -> Path:
        root = self._mask_artifact_root(image_id, instance_id, "mask_reviews")
        return root / "review.json"

    def _candidate_payload(self, image_id: str, candidate_path: Path | None) -> dict[str, Any] | None:
        if candidate_path is None:
            return None
        candidate = _read_json(candidate_path)
        if not candidate:
            return None
        return candidate

    def mask_review_payload(self, image_id: str) -> dict[str, Any]:
        img_path = self.image_path_for_id(image_id)
        ann = self.load_annotation(img_path).to_dict()
        objects = []
        for obj in ann.get("objects", []):
            instance_id = int(obj.get("instance_id") or 0)
            candidate_path = self._latest_candidate_path(image_id, instance_id)
            candidate = self._candidate_payload(image_id, candidate_path)
            current_signature = object_signature(ann, obj)
            if candidate is not None:
                candidate["stale"] = candidate.get("annotation_signature") != current_signature
            review = _read_json(self._review_path(image_id, instance_id))
            objects.append({
                "instance_id": instance_id,
                "candidate": candidate,
                "review": review,
            })
        return {"image_id": image_id, "image_key": self._make_image_key(img_path), "objects": objects}

    def generate_mask_candidate(self, image_id: str, instance_id: int) -> dict[str, Any]:
        img_path = self.image_path_for_id(image_id)
        ann = self.load_annotation(img_path).to_dict()
        obj = next((item for item in ann.get("objects", []) if int(item.get("instance_id") or 0) == int(instance_id)), None)
        if obj is None:
            raise DatasetError(f"Unknown object instance: {instance_id}")
        artifact_dir = self._mask_artifact_root(image_id, instance_id, "mask_candidates")
        try:
            candidate = generate_sam_mask_candidate(img_path, ann, obj, artifact_dir)
        except SamTeacherError as exc:
            raise MaskGenerationError(str(exc)) from exc
        candidate_path = artifact_dir / f"{candidate['candidate_id']}.json"
        _atomic_write_json(candidate_path, candidate)
        return self._candidate_payload(image_id, candidate_path) or candidate

    def save_mask_review(
        self,
        image_id: str,
        instance_id: int,
        user: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.image_path_for_id(image_id)
        score = int(payload.get("score"))
        if score < 0 or score > 3:
            raise DatasetError("Mask review score must be 0..3.")
        review_status = str(payload.get("review_status") or _review_status_from_score(score))
        review = {
            "schema_version": "mask_review_v1",
            "candidate_id": payload.get("candidate_id"),
            "instance_id": int(instance_id),
            "score": score,
            "review_status": review_status,
            "failure_tags": [str(tag) for tag in payload.get("failure_tags") or []],
            "notes": str(payload.get("notes") or ""),
            "reviewer": user,
            "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        _atomic_write_json(self._review_path(image_id, instance_id), review)
        return review

    def clear_mask_review(self, image_id: str, instance_id: int) -> dict[str, Any]:
        path = self._review_path(image_id, instance_id)
        if path.exists():
            path.unlink()
        return {"cleared": True, "instance_id": int(instance_id)}

    def mask_candidate_preview_path(self, image_id: str, instance_id: int) -> Path:
        candidate_path = self._latest_candidate_path(image_id, instance_id)
        candidate = _read_json(candidate_path) if candidate_path else None
        if not candidate:
            raise DatasetError("Mask candidate not found.")
        preview_name = candidate.get("preview_png")
        if not preview_name:
            raise DatasetError("Mask candidate preview not found.")
        preview_path = candidate_path.parent / str(preview_name)
        if not preview_path.exists():
            raise DatasetError("Mask candidate preview file is missing.")
        return preview_path

    def save_annotation(
        self,
        image_id: str,
        annotation_data: dict[str, Any],
        expected_etag: str,
    ) -> dict[str, Any]:
        img_path = self.image_path_for_id(image_id)
        ann_path = self._get_annotation_path(img_path)
        current_etag = _annotation_etag(ann_path)
        if expected_etag != current_etag:
            raise DatasetError("Annotation changed on disk; refresh before saving.")

        try:
            ann = AnnotationModel.from_dict(annotation_data, image_path=img_path)
        except Exception as exc:
            raise DatasetError(f"Invalid annotation JSON shape: {exc}") from exc

        if not ann.image_size or ann.image_size[0] <= 0 or ann.image_size[1] <= 0:
            try:
                with Image.open(img_path) as im:
                    ann.image_size = im.size
            except Exception:
                ann.image_size = (640, 480)
        if not ann.camera:
            ann.camera = img_path.parent.name

        image_key = self._make_image_key(img_path)
        validation = split_validation_messages(
            validate_annotation(ann, self.class_registry),
            image_key=image_key,
        )
        if validation["errors"]:
            raise DatasetValidationError(validation)

        ann.save(ann_path)
        self._annotation_meta[image_key] = (len(ann.objects), ann.axis_count())
        return {
            "annotation": ann.to_dict(),
            "etag": _annotation_etag(ann_path),
            "image_id": image_id,
            "image_key": self._make_image_key(img_path),
            "validation": {
                "valid": len(validation["errors"]) == 0,
                **validation,
            },
        }

    def validate_annotation_payload(self, img_path: Path) -> dict[str, list[dict[str, Any]]]:
        ann = self.load_annotation(img_path)
        return split_validation_messages(
            validate_annotation(ann, self.class_registry),
            image_key=self._make_image_key(img_path),
        )

    def image_entry(self, img_path: Path) -> ImageEntry:
        ann_path = self._get_annotation_path(img_path)
        image_key = self._make_image_key(img_path)
        object_count, axis_count = self._annotation_meta.get(image_key, (0, 0))
        if not ann_path.exists():
            status = "unannotated"
        elif object_count == 0:
            status = "empty"
        else:
            status = "annotated"
        return ImageEntry(
            image_id=encode_image_id(image_key),
            image_key=image_key,
            path=img_path,
            annotation_path=ann_path,
            status=status,
            object_count=object_count,
            axis_count=axis_count,
        )

    def list_images(self, status: str | None = None) -> list[ImageEntry]:
        entries = [self.image_entry(path) for path in self.image_paths]
        if status in {"legacy", "yaw_review", "mask_unreviewed", "mask_low_score"}:
            entries = [entry for entry in entries if self._matches_review_status(entry, status)]
        elif status and status != "all":
            entries = [entry for entry in entries if entry.status == status]
        return entries

    def _matches_review_status(self, entry: ImageEntry, status: str) -> bool:
        ann = self.load_annotation(entry.path).to_dict()
        objects = ann.get("objects", [])
        if status == "legacy":
            return any(str(obj.get("class_name") or "").endswith(LEGACY_CLASS_SUFFIX) for obj in objects)
        if status == "yaw_review":
            for obj in objects:
                class_name = str(obj.get("class_name") or "")
                has_axis = bool(obj.get("main_axis_points"))
                if class_name in YAW_SENSITIVE_CLASSES and not has_axis:
                    return True
            return False
        if status == "mask_unreviewed":
            for obj in objects:
                instance_id = int(obj.get("instance_id") or 0)
                if self._latest_candidate_path(entry.image_id, instance_id) and not self._review_path(entry.image_id, instance_id).exists():
                    return True
            return False
        if status == "mask_low_score":
            for obj in objects:
                instance_id = int(obj.get("instance_id") or 0)
                review = _read_json(self._review_path(entry.image_id, instance_id))
                if review and int(review.get("score") or 0) <= 2:
                    return True
            return False
        return False

    def stats(self) -> dict[str, Any]:
        class_rows: dict[int, dict[str, Any]] = {}
        image_rows: list[dict[str, Any]] = []
        all_issues: list[dict[str, Any]] = []
        dataset_objects = 0
        dataset_axis_count = 0
        dataset_errors = 0
        dataset_warnings = 0
        annotated_images = 0
        empty_images = 0
        unannotated_images = 0

        if self.class_registry is not None:
            for cls in self.class_registry.all_classes():
                class_rows[int(cls.id)] = {
                    "class_id": int(cls.id),
                    "class_name": cls.name,
                    "graspable": bool(cls.graspable),
                    "image_keys": set(),
                    "object_count": 0,
                    "axis_count": 0,
                    "yaw_valid_count": 0,
                    "yaw_status_counts": {"valid": 0, "not_required": 0, "ambiguous": 0, "occluded": 0, "optional": 0},
                    "occlusion_counts": {0: 0, 1: 0, 2: 0, 3: 0},
                    "difficulty_counts": {"easy": 0, "medium": 0, "hard": 0},
                    "obb_count": 0,
                    "error_count": 0,
                    "warning_count": 0,
                }

        for img_path in self.image_paths:
            entry = self.image_entry(img_path)
            if entry.status == "annotated":
                annotated_images += 1
            elif entry.status == "empty":
                empty_images += 1
            else:
                unannotated_images += 1
            ann = self.load_annotation(img_path)
            image_key = self._make_image_key(img_path)
            validation = split_validation_messages(
                validate_annotation(ann, self.class_registry),
                image_key=image_key,
            )
            dataset_errors += len(validation["errors"])
            dataset_warnings += len(validation["warnings"])
            all_issues.extend(validation["errors"])
            all_issues.extend(validation["warnings"])
            dataset_objects += len(ann.objects)
            dataset_axis_count += ann.axis_count()

            instance_classes = {obj.instance_id: obj.class_id for obj in ann.objects}
            for severity, messages in (("error_count", validation["errors"]), ("warning_count", validation["warnings"])):
                for issue in messages:
                    instance_id = issue.get("instance_id")
                    if instance_id is None:
                        continue
                    class_id = instance_classes.get(int(instance_id))
                    if class_id is not None and class_id in class_rows:
                        class_rows[class_id][severity] += 1

            image_rows.append(
                {
                    **entry.to_dict(),
                    "error_count": len(validation["errors"]),
                    "warning_count": len(validation["warnings"]),
                }
            )

            for obj in ann.objects:
                class_id = int(obj.class_id)
                class_name = obj.class_name or f"class_{obj.class_id}"
                row = class_rows.setdefault(
                    class_id,
                    {
                        "class_id": class_id,
                        "class_name": class_name,
                        "graspable": bool(obj.graspable),
                        "image_keys": set(),
                        "object_count": 0,
                        "axis_count": 0,
                        "yaw_valid_count": 0,
                        "yaw_status_counts": {"valid": 0, "not_required": 0, "ambiguous": 0, "occluded": 0, "optional": 0},
                        "occlusion_counts": {0: 0, 1: 0, 2: 0, 3: 0},
                        "difficulty_counts": {"easy": 0, "medium": 0, "hard": 0},
                        "obb_count": 0,
                        "error_count": 0,
                        "warning_count": 0,
                    },
                )
                if not row["class_name"] or row["class_name"].startswith("class_"):
                    row["class_name"] = class_name
                row["graspable"] = bool(obj.graspable)
                row["image_keys"].add(image_key)
                row["object_count"] += 1

                # Axis stats
                if obj.has_axis:
                    row["axis_count"] += 1

                # Yaw status counts
                yaw_status = obj.yaw_label_status
                if yaw_status in row["yaw_status_counts"]:
                    row["yaw_status_counts"][yaw_status] += 1
                if yaw_status == "valid":
                    row["yaw_valid_count"] += 1

                # Occlusion counts
                occ = obj.occlusion_level
                if occ in row["occlusion_counts"]:
                    row["occlusion_counts"][occ] += 1

                # Difficulty counts
                diff = obj.difficulty
                if diff in row["difficulty_counts"]:
                    row["difficulty_counts"][diff] += 1

                # OBB count
                if obj.has_obb:
                    row["obb_count"] += 1

        class_stats = []
        for row in class_rows.values():
            object_count = row["object_count"]
            class_stats.append(
                {
                    "class_id": row["class_id"],
                    "class_name": row["class_name"],
                    "graspable": row["graspable"],
                    "image_count": len(row["image_keys"]),
                    "object_count": object_count,
                    "axis_count": row["axis_count"],
                    "yaw_valid_count": row["yaw_valid_count"],
                    "yaw_status_counts": row["yaw_status_counts"],
                    "occlusion_counts": row["occlusion_counts"],
                    "difficulty_counts": row["difficulty_counts"],
                    "obb_count": row["obb_count"],
                    "object_share": object_count / dataset_objects if dataset_objects else 0.0,
                    "error_count": row["error_count"],
                    "warning_count": row["warning_count"],
                    "suggestions": _class_suggestions_v2(row),
                }
            )

        class_stats.sort(key=lambda item: item["class_id"])
        image_rows.sort(key=lambda item: (-item["error_count"], -item["warning_count"], item["image_key"]))
        return {
            "dataset": {
                "image_count": len(self.image_paths),
                "annotated_image_count": annotated_images,
                "empty_image_count": empty_images,
                "unannotated_image_count": unannotated_images,
                "class_count": len(class_stats),
                "object_count": dataset_objects,
                "axis_count": dataset_axis_count,
                "error_count": dataset_errors,
                "warning_count": dataset_warnings,
            },
            "classes": class_stats,
            "images": image_rows,
            "issues": all_issues[:500],
        }

    def delete_image(self, image_id: str) -> dict[str, Any]:
        img_path = self.image_path_for_id(image_id)
        image_key = self._make_image_key(img_path)
        ann_path = self._get_annotation_path(img_path)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        trash_root = self.root / ".aga_trash" / stamp
        trash_image_path = _unique_path(trash_root / "images" / Path(image_key))
        trash_image_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(img_path), str(trash_image_path))

        trash_annotation_path: Path | None = None
        if ann_path.exists():
            try:
                ann_rel = ann_path.relative_to(self.annotations_dir)
            except ValueError:
                ann_rel = Path(ann_path.name)
            trash_annotation_path = _unique_path(trash_root / "annotations" / ann_rel)
            trash_annotation_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(ann_path), str(trash_annotation_path))

        self._image_paths = [path for path in self._image_paths if path != img_path]
        self._image_by_key = {self._make_image_key(path): path for path in self._image_paths}
        self._annotation_meta.pop(image_key, None)
        return {
            "image_id": image_id,
            "image_key": image_key,
            "trash_image_path": str(trash_image_path),
            "trash_annotation_path": str(trash_annotation_path) if trash_annotation_path else None,
        }

    def add_uploaded_images(self, files: list[Any], camera_name: str = "camera_1") -> int:
        camera = _slugify(camera_name or "camera_1")
        images_dir = self.root / "images" / camera
        images_dir.mkdir(parents=True, exist_ok=True)
        copied = 0
        next_index = len([path for path in images_dir.iterdir() if path.is_file()]) + 1
        for upload in files:
            suffix = Path(upload.filename or "").suffix.lower()
            if suffix not in IMAGE_EXTENSIONS:
                continue
            while True:
                target = images_dir / f"{next_index:06d}{suffix}"
                next_index += 1
                if not target.exists():
                    break
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                shutil.copyfileobj(upload.file, tmp)
                tmp_path = Path(tmp.name)
            shutil.move(str(tmp_path), target)
            copied += 1
        if copied == 0:
            raise DatasetError("No supported images were uploaded.")
        self._refresh_images()
        return copied

    def add_assembled_images(self, files: list[AssembledUpload], camera_name: str = "camera_1") -> int:
        camera = _slugify(camera_name or "camera_1")
        images_dir = self.root / "images" / camera
        images_dir.mkdir(parents=True, exist_ok=True)
        copied = 0
        next_index = len([path for path in images_dir.iterdir() if path.is_file()]) + 1
        for upload in files:
            suffix = Path(upload.filename).suffix.lower()
            if suffix not in IMAGE_EXTENSIONS:
                continue
            while True:
                target = images_dir / f"{next_index:06d}{suffix}"
                next_index += 1
                if not target.exists():
                    break
            shutil.copyfile(upload.path, target)
            copied += 1
        if copied == 0:
            raise DatasetError("No supported images were uploaded.")
        self._refresh_images()
        return copied

    def class_list(self) -> list[dict[str, Any]]:
        if self.class_registry is None:
            return []
        return [cls.to_dict() for cls in self.class_registry.all_classes()]

    def save_classes(self, classes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = _normalize_classes(classes)
        self.classes_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", dir=str(self.classes_path.parent)) as tmp:
            yaml.safe_dump(
                {"classes": normalized},
                tmp,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )
            tmp_path = Path(tmp.name)
        tmp_path.replace(self.classes_path)
        self._classes = self._load_classes()
        return self.class_list()

    def metadata(self, dataset_id: str, source: str = "server", name: str | None = None) -> dict[str, Any]:
        entries = self.list_images()
        annotated = len([e for e in entries if e.status == "annotated"])
        empty = len([e for e in entries if e.status == "empty"])
        return {
            "dataset_id": dataset_id,
            "name": name or self.root.name,
            "root": str(self.root),
            "source": source,
            "image_count": len(entries),
            "annotated": annotated,
            "empty": empty,
            "unannotated": len(entries) - annotated - empty,
            "classes": self.class_list(),
        }


class DatasetService:
    def __init__(self, config: WebConfig, store: StateStore):
        self.config = config
        self.store = store
        self._cache: OrderedDict[str, WebDataset] = OrderedDict()
        self._max_cache = 32

    def _cached_dataset(self, root: Path) -> WebDataset:
        key = str(root.resolve())
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        while len(self._cache) >= self._max_cache:
            self._cache.popitem(last=False)
        ds = WebDataset(root)
        self._cache[key] = ds
        self._cache.move_to_end(key)
        return ds

    def _invalidate_cache(self, root: Path) -> None:
        self._cache.pop(str(root.resolve()), None)

    @property
    def managed_root(self) -> Path:
        return self.config.upload_root

    def roots(self) -> list[dict[str, str]]:
        return [{"path": str(root), "name": root.name or str(root)} for root in self.config.dataset_roots]

    def _sync_discovered_datasets(self) -> None:
        rows = self.store.list_datasets()
        known_roots = {Path(row["root"]).resolve() for row in rows}
        library_roots = {root.resolve() for root in self.config.dataset_roots + [self.config.upload_root]}
        for library_root in library_roots:
            if not library_root.is_dir():
                continue
            for child in library_root.iterdir():
                if not child.is_dir() or child.name.startswith("."):
                    continue
                if child.name in IGNORED_SCAN_DIRS:
                    continue
                resolved = child.resolve()
                if resolved in known_roots or not _looks_like_dataset_root(resolved):
                    continue
                self.store.register_dataset(resolved, child.name, "managed")
                known_roots.add(resolved)

    def _metadata_from_row(self, row: dict[str, Any]) -> dict[str, Any]:
        root = Path(row["root"])
        if not root.exists():
            return {
                "dataset_id": row["id"],
                "name": row["name"],
                "root": str(root),
                "source": row["source"],
                "image_count": 0,
                "annotated": 0,
                "empty": 0,
                "unannotated": 0,
                "classes": [],
                "missing": True,
            }
        dataset = WebDataset(root)
        return dataset.metadata(row["id"], row["source"], row["name"])

    def list_datasets(self) -> list[dict[str, Any]]:
        self._sync_discovered_datasets()
        rows = self.store.list_datasets()
        return [self._metadata_from_row(row) for row in rows]

    def clear_cache_for(self, root: Path) -> None:
        key = str(root.resolve())
        if key in self._cache:
            self._cache[key]._refresh_images()
            self._cache.pop(key, None)

    def open_dataset(self, path: str | Path, source: str = "server") -> dict[str, Any]:
        root = resolve_allowed_path(path, self.config.dataset_roots + [self.config.upload_root])
        dataset = WebDataset(root)
        row = self.store.register_dataset(root, root.name, source)
        return dataset.metadata(row["id"], row["source"], row["name"])

    def get_dataset(self, dataset_id: str) -> tuple[dict[str, Any], WebDataset]:
        row = self.store.get_dataset(dataset_id)
        if row is None:
            raise DatasetError(f"Unknown dataset: {dataset_id}")
        dataset = self._cached_dataset(Path(row["root"]))
        return row, dataset

    def create_dataset(
        self,
        name: str,
        camera_name: str = "camera_1",
        classes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        display_name = name.strip()
        if not display_name:
            raise DatasetError("Dataset name is required.")
        dataset_name = _slugify(display_name)
        camera = _slugify(camera_name or "camera_1")
        root = self.managed_root / dataset_name
        if root.exists():
            root = self.managed_root / f"{dataset_name}_{len(list(self.managed_root.glob(dataset_name + '*'))) + 1}"
        _create_standard_dataset_dirs(root, camera)
        normalized = _normalize_classes(classes or [])
        with open(root / "classes.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump({"classes": normalized}, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        row = self.store.register_dataset(root, display_name, "managed")
        dataset = WebDataset(root)
        return dataset.metadata(row["id"], row["source"], row["name"])

    def rename_dataset(self, dataset_id: str, name: str) -> dict[str, Any]:
        display_name = name.strip()
        if not display_name:
            raise DatasetError("Dataset name is required.")
        row = self.store.update_dataset_name(dataset_id, display_name)
        if row is None:
            raise DatasetError(f"Unknown dataset: {dataset_id}")
        return self._metadata_from_row(row)

    def delete_dataset(self, dataset_id: str) -> dict[str, Any]:
        row = self.store.get_dataset(dataset_id)
        if row is None:
            raise DatasetError(f"Unknown dataset: {dataset_id}")
        root = Path(row["root"]).resolve()
        protected_roots = {path.resolve() for path in self.config.dataset_roots + [self.config.upload_root]}
        if root in protected_roots:
            raise DatasetError("Refusing to delete the configured dataset library root.")

        deleted: dict[str, Any] = {
            "dataset_id": dataset_id,
            "name": row["name"],
            "root": str(root),
            "trash_path": None,
        }
        if root.exists():
            resolve_allowed_path(root, self.config.dataset_roots + [self.config.upload_root])
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            trash_root = root.parent / ".aga_trash" / "datasets" / stamp
            trash_path = _unique_path(trash_root / root.name)
            trash_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(root), str(trash_path))
            deleted["trash_path"] = str(trash_path)
        self.store.delete_dataset_state(dataset_id)
        return deleted

    def upload_dataset(
        self,
        name: str,
        camera_name: str,
        classes_json: str,
        files: list[Any],
    ) -> dict[str, Any]:
        dataset_name = _slugify(name)
        camera = _slugify(camera_name or "camera_1")
        root = self.config.upload_root / dataset_name
        if root.exists():
            root = self.config.upload_root / f"{dataset_name}_{len(list(self.config.upload_root.glob(dataset_name + '*'))) + 1}"
        _create_standard_dataset_dirs(root, camera)
        images_dir = root / "images" / camera

        copied = WebDataset(root).add_uploaded_images(files, camera)

        classes: list[dict[str, Any]]
        if classes_json.strip():
            loaded = json.loads(classes_json)
            classes = loaded["classes"] if isinstance(loaded, dict) and "classes" in loaded else loaded
        else:
            classes = []
        classes = _normalize_classes(classes)
        with open(root / "classes.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump({"classes": classes}, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        row = self.store.register_dataset(root, name.strip() or root.name, "upload")
        dataset = WebDataset(root)
        return dataset.metadata(row["id"], "upload", row["name"])

    def upload_dataset_from_assembled(
        self,
        name: str,
        camera_name: str,
        classes: list[dict[str, Any]],
        files: list[AssembledUpload],
    ) -> dict[str, Any]:
        dataset_name = _slugify(name)
        camera = _slugify(camera_name or "camera_1")
        root = self.config.upload_root / dataset_name
        if root.exists():
            root = self.config.upload_root / f"{dataset_name}_{len(list(self.config.upload_root.glob(dataset_name + '*'))) + 1}"
        _create_standard_dataset_dirs(root, camera)
        WebDataset(root).add_assembled_images(files, camera)

        normalized = _normalize_classes(classes)
        with open(root / "classes.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump({"classes": normalized}, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        row = self.store.register_dataset(root, name.strip() or root.name, "upload")
        dataset = WebDataset(root)
        return dataset.metadata(row["id"], "upload", row["name"])

"""Dataset filesystem service used by the FastAPI app."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from PIL import Image

from assistive_grasp_annotator.models.annotation import AnnotationModel
from assistive_grasp_annotator.models.classes import ClassRegistry
from assistive_grasp_annotator.tools.validators import validate_annotation
from assistive_grasp_annotator.web.config import WebConfig, resolve_allowed_path
from assistive_grasp_annotator.web.ids import decode_image_id, encode_image_id
from assistive_grasp_annotator.web.state import StateStore
from assistive_grasp_annotator.web.uploads import AssembledUpload


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
CLASS_POLICIES = {"grasp_rect", "center_or_grasp_rect", "report_only"}
IGNORED_SCAN_DIRS = {"annotations", "generated", "splits", ".aga_trash"}


class DatasetError(ValueError):
    pass


def split_validation_messages(messages: list[str]) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for message in messages:
        if "WARNING" in message:
            warnings.append(message.replace(" (WARNING)", "").replace("WARNING: ", ""))
        else:
            errors.append(message)
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
        if name in seen_names:
            raise DatasetError(f"Duplicate class name: {name}")
        policy = str(raw.get("policy") or "grasp_rect").strip()
        if policy not in CLASS_POLICIES:
            raise DatasetError(f"Unsupported class policy: {policy}")
        normalized.append(
            {
                "id": class_id,
                "name": name,
                "graspable": bool(raw.get("graspable", True)),
                "policy": policy,
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


@dataclass(frozen=True)
class ImageEntry:
    image_id: str
    image_key: str
    path: Path
    annotation_path: Path
    status: str
    object_count: int
    grasp_count: int

    def to_dict(self, lock: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "image_key": self.image_key,
            "status": self.status,
            "object_count": self.object_count,
            "grasp_count": self.grasp_count,
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

        validation = split_validation_messages(validate_annotation(ann, self.class_registry))

        ann.save(ann_path)
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

    def validate_annotation_payload(self, img_path: Path) -> dict[str, list[str]]:
        ann = self.load_annotation(img_path)
        return split_validation_messages(validate_annotation(ann, self.class_registry))

    def image_entry(self, img_path: Path) -> ImageEntry:
        ann_path = self._get_annotation_path(img_path)
        object_count = 0
        grasp_count = 0
        if ann_path.exists():
            try:
                ann = self.load_annotation(img_path)
                object_count = len(ann.objects)
                grasp_count = ann.grasp_count()
            except Exception:
                pass
        if not ann_path.exists():
            status = "unannotated"
        elif object_count == 0:
            status = "empty"
        else:
            status = "annotated"
        image_key = self._make_image_key(img_path)
        return ImageEntry(
            image_id=encode_image_id(image_key),
            image_key=image_key,
            path=img_path,
            annotation_path=ann_path,
            status=status,
            object_count=object_count,
            grasp_count=grasp_count,
        )

    def list_images(self, status: str | None = None) -> list[ImageEntry]:
        entries = [self.image_entry(path) for path in self.image_paths]
        if status and status != "all":
            entries = [entry for entry in entries if entry.status == status]
        return entries

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

    def open_dataset(self, path: str | Path, source: str = "server") -> dict[str, Any]:
        root = resolve_allowed_path(path, self.config.dataset_roots + [self.config.upload_root])
        dataset = WebDataset(root)
        row = self.store.register_dataset(root, root.name, source)
        return dataset.metadata(row["id"], row["source"], row["name"])

    def get_dataset(self, dataset_id: str) -> tuple[dict[str, Any], WebDataset]:
        row = self.store.get_dataset(dataset_id)
        if row is None:
            raise DatasetError(f"Unknown dataset: {dataset_id}")
        dataset = WebDataset(row["root"])
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

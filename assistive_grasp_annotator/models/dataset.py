"""Dataset model — manages the dataset directory on disk."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from assistive_grasp_annotator.models.annotation import AnnotationModel
from assistive_grasp_annotator.models.classes import ClassRegistry


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}


class DatasetModel(QObject):
    """Manages dataset directory: images, annotations, splits, classes."""

    dataset_opened = Signal()
    dataset_closed = Signal()
    image_list_changed = Signal()
    current_image_changed = Signal(str, object)  # image_key, AnnotationModel

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dataset_path: Optional[Path] = None
        self._annotations_dir: Optional[Path] = None
        self._classes: Optional[ClassRegistry] = None
        self._image_paths: list[Path] = []
        self._current_index: int = -1
        self._annotations: dict[str, AnnotationModel] = {}  # keyed by image_key

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def dataset_path(self) -> Optional[Path]:
        return self._dataset_path

    @property
    def class_registry(self) -> Optional[ClassRegistry]:
        return self._classes

    @property
    def image_paths(self) -> list[Path]:
        return self._image_paths

    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    def current_image_path(self) -> Optional[Path]:
        if 0 <= self._current_index < len(self._image_paths):
            return self._image_paths[self._current_index]
        return None

    @property
    def image_count(self) -> int:
        return len(self._image_paths)

    # ------------------------------------------------------------------
    # Open / Close
    # ------------------------------------------------------------------

    def open_dataset(self, path: str | Path) -> bool:
        root = Path(path)
        if not root.is_dir():
            return False

        images_subdir = root / "images"
        classes_yaml = root / "classes.yaml"
        annotations_subdir = root / "annotations"

        self._dataset_path = root

        # Load classes.yaml (optional — can be created later)
        self._classes = None
        if classes_yaml.exists():
            try:
                self._classes = ClassRegistry.from_yaml(classes_yaml)
            except Exception:
                pass

        # Scan for images:
        #   Prefer images/ subdirectory if it exists,
        #   otherwise scan the root folder itself.
        if images_subdir.is_dir():
            scan_root = images_subdir
        else:
            scan_root = root

        self._image_paths = []
        for ext in IMAGE_EXTENSIONS:
            self._image_paths.extend(scan_root.rglob(f"*{ext}"))
            self._image_paths.extend(scan_root.rglob(f"*{ext.upper()}"))
        self._image_paths = sorted(set(self._image_paths))

        if not self._image_paths:
            self._dataset_path = None
            return False

        # Ensure annotations directory exists
        if annotations_subdir.is_dir():
            self._annotations_dir = annotations_subdir
        elif images_subdir.is_dir():
            self._annotations_dir = root / "annotations"
        else:
            self._annotations_dir = root / "annotations"

        self._annotations.clear()
        self._current_index = -1

        self.dataset_opened.emit()
        self.image_list_changed.emit()

        if self._image_paths:
            self.select_image(0)
        return True

    def close_dataset(self):
        self._dataset_path = None
        self._annotations_dir = None
        self._classes = None
        self._image_paths = []
        self._current_index = -1
        self._annotations.clear()
        self.dataset_closed.emit()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def select_image(self, index: int) -> bool:
        if index < 0 or index >= len(self._image_paths):
            return False
        self._current_index = index
        img_path = self._image_paths[index]
        image_key = self._make_image_key(img_path)
        ann = self.load_annotation(img_path)
        self.current_image_changed.emit(image_key, ann)
        return True

    def next_image(self) -> bool:
        if self._current_index + 1 < len(self._image_paths):
            return self.select_image(self._current_index + 1)
        return False

    def prev_image(self) -> bool:
        if self._current_index > 0:
            return self.select_image(self._current_index - 1)
        return False

    # ------------------------------------------------------------------
    # Annotation loading
    # ------------------------------------------------------------------

    def _make_image_key(self, img_path: Path) -> str:
        if self._dataset_path is None:
            return img_path.stem

        # Try relative to images/ subdirectory first
        images_dir = self._dataset_path / "images"
        try:
            return str(img_path.relative_to(images_dir))
        except ValueError:
            pass

        # Try relative to dataset root
        try:
            return str(img_path.relative_to(self._dataset_path))
        except ValueError:
            return img_path.stem

    def _get_annotation_path(self, img_path: Path) -> Path:
        """Map an image path to its annotation JSON path under annotations_dir/."""
        if self._annotations_dir is None:
            return img_path.with_suffix(".json")

        # Determine the relative path from whichever image root was used
        images_dir = self._dataset_path / "images" if self._dataset_path else None
        scan_root = images_dir if (images_dir and images_dir.is_dir()) else self._dataset_path

        try:
            rel = img_path.relative_to(scan_root) if scan_root else None
        except ValueError:
            rel = None

        if rel is not None:
            return self._annotations_dir / rel.with_suffix(".json")
        return self._annotations_dir / (img_path.stem + ".json")

    def load_annotation(self, img_path: Path) -> AnnotationModel:
        image_key = self._make_image_key(img_path)

        if image_key in self._annotations:
            return self._annotations[image_key]

        ann_path = self._get_annotation_path(img_path)
        if ann_path.exists():
            try:
                ann = AnnotationModel.load(ann_path)
                ann.image_path = img_path
                self._annotations[image_key] = ann
                return ann
            except Exception:
                pass

        # Create fresh annotation
        from PIL import Image
        ann = AnnotationModel(image_path=img_path)
        try:
            with Image.open(img_path) as im:
                ann.image_size = im.size
        except Exception:
            ann.image_size = (640, 480)

        ann.camera = img_path.parent.name if img_path.parent else ""
        self._annotations[image_key] = ann
        return ann

    def save_current_annotation(self) -> bool:
        if self._dataset_path is None or self.current_image_path is None:
            return False
        ann = self._annotations.get(self._make_image_key(self.current_image_path))
        if ann is None:
            return False
        ann_path = self._get_annotation_path(self.current_image_path)
        ann.save(ann_path)
        return True

    def save_all_annotations(self) -> tuple[int, int]:
        saved = 0
        errors = 0
        for img_path in self._image_paths:
            image_key = self._make_image_key(img_path)
            ann = self._annotations.get(image_key)
            if ann is None or not ann.dirty:
                continue
            try:
                ann_path = self._get_annotation_path(img_path)
                ann.save(ann_path)
                saved += 1
            except Exception:
                errors += 1
        return (saved, errors)

    def get_current_annotation(self) -> Optional[AnnotationModel]:
        if self.current_image_path is None:
            return None
        return self._annotations.get(self._make_image_key(self.current_image_path))

    def current_annotation_key(self) -> str:
        if self.current_image_path is None:
            return ""
        return self._make_image_key(self.current_image_path)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Static factory — create dataset from raw image folder
    # ------------------------------------------------------------------

    @staticmethod
    def create_dataset(
        root_path: Path,
        image_source_dir: Path,
        camera_name: str = "camera_1",
        copy_images: bool = False,
        classes: list[dict] | None = None,
    ) -> Optional[DatasetModel]:
        """
        Create a standardized dataset directory structure from raw images.

        If copy_images is True: images are copied to root_path/images/{camera_name}/.
        If False: images are moved into images/{camera_name}/ at root_path,
                  or if root_path == image_source_dir, images stay in place
                  under images/{camera_name}/.

        A classes.yaml template is written to root_path/.

        Returns a DatasetModel already opened on the new dataset, or None on failure.
        """
        root_path = Path(root_path)
        image_source_dir = Path(image_source_dir)
        images_dest = root_path / "images" / camera_name
        images_dest.mkdir(parents=True, exist_ok=True)

        # Gather source images
        img_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
        source_images: list[Path] = []
        for ext in img_exts:
            source_images.extend(image_source_dir.rglob(f"*{ext}"))
            source_images.extend(image_source_dir.rglob(f"*{ext.upper()}"))
        source_images = sorted(set(source_images))

        if not source_images:
            return None

        if copy_images or root_path.resolve() != image_source_dir.resolve():
            for i, img in enumerate(source_images, 1):
                ext = img.suffix.lower()
                dst = images_dest / f"{i:06d}{ext}"
                while dst.exists():
                    i += 1
                    dst = images_dest / f"{i:06d}{ext}"
                shutil.copy2(str(img), str(dst))
        else:
            # In-place: move images into images/{camera_name}/
            for img in source_images:
                dst = images_dest / img.name
                if img.resolve() == dst.resolve():
                    continue
                if not dst.exists():
                    try:
                        os.replace(str(img), str(dst))
                    except OSError:
                        shutil.copy2(str(img), str(dst))

        # Create ancillary directories
        (root_path / "annotations").mkdir(parents=True, exist_ok=True)
        (root_path / "splits").mkdir(parents=True, exist_ok=True)
        (root_path / "generated").mkdir(parents=True, exist_ok=True)

        # Write classes.yaml
        if classes is None:
            classes = []
        classes_yaml = root_path / "classes.yaml"
        if not classes_yaml.exists():
            import yaml
            data = {"classes": classes}
            with open(classes_yaml, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        # Open and return
        ds = DatasetModel()
        ok = ds.open_dataset(str(root_path))
        return ds if ok else None

    def get_annotation_status(self) -> dict[str, int]:
        total = len(self._image_paths)
        annotated = 0
        for img_path in self._image_paths:
            # Annotated = has at least one object or has a saved JSON
            ann_path = self._get_annotation_path(img_path)
            if ann_path.exists():
                annotated += 1
            else:
                image_key = self._make_image_key(img_path)
                ann = self._annotations.get(image_key)
                if ann and len(ann.objects) > 0:
                    annotated += 1
        return {"total": total, "annotated": annotated, "unannotated": total - annotated}

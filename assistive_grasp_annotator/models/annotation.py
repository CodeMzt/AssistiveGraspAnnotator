"""Data model for per-image annotations — ObjectAnnotation, GraspAnnotation, AnnotationModel."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from PySide6.QtCore import QObject, Signal
except ImportError:
    from PySide6.QtCore import QObject, Signal  # type: ignore[no-redef]

from assistive_grasp_annotator.tools.geometry import compute_p3, point_in_bbox


DIFFICULTY_MAP: dict[str, float] = {
    "easy": 1.0,
    "medium": 0.7,
    "hard": 0.4,
    "invalid": 0.0,
}

QUALITY_TO_DIFFICULTY: dict[float, str] = {
    1.0: "easy",
    0.7: "medium",
    0.4: "hard",
    0.0: "invalid",
}


@dataclass
class GraspAnnotation:
    grasp_id: int
    points: list[list[float]]  # [[x0,y0],[x1,y1],[x2,y2],[x3,y3]]
    axis_convention: str = "p0_to_p1_is_grasp_width_axis"
    quality: float = 1.0
    difficulty: str = "easy"
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "grasp_id": self.grasp_id,
            "points": self.points,
            "axis_convention": self.axis_convention,
            "quality": self.quality,
            "difficulty": self.difficulty,
            "note": self.note,
        }

    @staticmethod
    def from_dict(data: dict) -> GraspAnnotation:
        return GraspAnnotation(
            grasp_id=data["grasp_id"],
            points=data["points"],
            axis_convention=data.get("axis_convention", "p0_to_p1_is_grasp_width_axis"),
            quality=data.get("quality", 1.0),
            difficulty=data.get("difficulty", "easy"),
            note=data.get("note", ""),
        )

    @property
    def quality_from_difficulty(self) -> float:
        return DIFFICULTY_MAP.get(self.difficulty, 0.0)

    def flatten_points(self) -> list[tuple[float, float]]:
        return [(p[0], p[1]) for p in self.points]

    def set_points_from_flat(self, flat: list[tuple[float, float]]):
        self.points = [[p[0], p[1]] for p in flat]


@dataclass
class ObjectAnnotation:
    instance_id: int
    class_id: int
    class_name: str = ""
    bbox_xyxy: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    graspable: bool = True
    policy: str = "grasp_rect"
    grasps: list[GraspAnnotation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "class_id": self.class_id,
            "class_name": self.class_name,
            "bbox_xyxy": self.bbox_xyxy,
            "graspable": self.graspable,
            "policy": self.policy,
            "grasps": [g.to_dict() for g in self.grasps],
        }

    @staticmethod
    def from_dict(data: dict) -> ObjectAnnotation:
        obj = ObjectAnnotation(
            instance_id=data["instance_id"],
            class_id=data["class_id"],
            class_name=data.get("class_name", ""),
            bbox_xyxy=data.get("bbox_xyxy", [0, 0, 0, 0]),
            graspable=data.get("graspable", True),
            policy=data.get("policy", "grasp_rect"),
        )
        for gd in data.get("grasps", []):
            obj.grasps.append(GraspAnnotation.from_dict(gd))
        return obj

    def next_grasp_id(self) -> int:
        if not self.grasps:
            return 1
        return max(g.grasp_id for g in self.grasps) + 1


class AnnotationModel(QObject):
    """Per-image annotation model. Manages objects and grasps for one image."""

    objects_changed = Signal()
    grasps_changed = Signal()
    annotation_modified = Signal()
    object_selection_requested = Signal(int)  # instance_id

    def __init__(
        self,
        image_path: str | Path | None = None,
        image_size: tuple[int, int] | None = None,
        camera: str = "",
        source: str = "",
        split: str = "train",
        parent=None,
    ):
        super().__init__(parent)
        self.image_path: Path | None = Path(image_path) if image_path else None
        self.image_size: tuple[int, int] | None = image_size
        self.camera: str = camera
        self.source: str = source
        self.split: str = split
        self.objects: list[ObjectAnnotation] = []
        self._next_instance_id: int = 1
        self.dirty: bool = False

    # ------------------------------------------------------------------
    # Object management
    # ------------------------------------------------------------------

    def add_object(
        self, class_id: int, bbox: list[float],
        class_name: str = "", graspable: bool = True, policy: str = "grasp_rect",
    ) -> ObjectAnnotation:
        obj = ObjectAnnotation(
            instance_id=self._next_instance_id,
            class_id=class_id,
            class_name=class_name,
            bbox_xyxy=[float(v) for v in bbox],
            graspable=graspable,
            policy=policy,
        )
        self._next_instance_id += 1
        self.objects.append(obj)
        self.dirty = True
        self.objects_changed.emit()
        self.annotation_modified.emit()
        return obj

    def remove_object(self, instance_id: int) -> bool:
        for i, obj in enumerate(self.objects):
            if obj.instance_id == instance_id:
                del self.objects[i]
                self._compact_instance_ids()
                self.dirty = True
                self.objects_changed.emit()
                self.annotation_modified.emit()
                return True
        return False

    def _compact_instance_ids(self):
        """Reassign sequential instance_ids starting from 1."""
        for i, obj in enumerate(self.objects, 1):
            obj.instance_id = i
        self._next_instance_id = len(self.objects) + 1

    def update_object_bbox(self, instance_id: int, new_bbox: list[float]) -> bool:
        obj = self.get_object_by_instance(instance_id)
        if obj is None:
            return False
        obj.bbox_xyxy = [float(v) for v in new_bbox]
        self.dirty = True
        self.annotation_modified.emit()
        return True

    def update_object_class(
        self, instance_id: int, class_id: int, class_name: str = "",
        graspable: bool = True, policy: str = "grasp_rect",
    ) -> bool:
        obj = self.get_object_by_instance(instance_id)
        if obj is None:
            return False
        obj.class_id = class_id
        obj.class_name = class_name or obj.class_name
        obj.graspable = graspable
        obj.policy = policy
        self.dirty = True
        self.objects_changed.emit()
        self.annotation_modified.emit()
        return True

    # ------------------------------------------------------------------
    # Grasp management
    # ------------------------------------------------------------------

    def add_grasp(self, instance_id: int, points: list[list[float]]) -> Optional[GraspAnnotation]:
        obj = self.get_object_by_instance(instance_id)
        if obj is None:
            return None
        # If only 3 points, compute p3
        pts = [[float(p[0]), float(p[1])] for p in points]
        if len(pts) == 3:
            p3 = compute_p3(
                (pts[0][0], pts[0][1]),
                (pts[1][0], pts[1][1]),
                (pts[2][0], pts[2][1]),
            )
            pts.append([p3[0], p3[1]])
        grasp = GraspAnnotation(
            grasp_id=obj.next_grasp_id(),
            points=pts,
        )
        obj.grasps.append(grasp)
        self.dirty = True
        self.grasps_changed.emit()
        self.annotation_modified.emit()
        return grasp

    def remove_grasp(self, instance_id: int, grasp_id: int) -> bool:
        obj = self.get_object_by_instance(instance_id)
        if obj is None:
            return False
        for i, g in enumerate(obj.grasps):
            if g.grasp_id == grasp_id:
                del obj.grasps[i]
                self.dirty = True
                self.grasps_changed.emit()
                self.annotation_modified.emit()
                return True
        return False

    def update_grasp_points(self, instance_id: int, grasp_id: int,
                            points: list[list[float]]) -> bool:
        grasp = self.get_grasp(instance_id, grasp_id)
        if grasp is None:
            return False
        grasp.points = [[float(p[0]), float(p[1])] for p in points]
        self.dirty = True
        self.annotation_modified.emit()
        return True

    def update_grasp_metadata(
        self, instance_id: int, grasp_id: int,
        quality: float | None = None,
        difficulty: str | None = None,
        note: str | None = None,
    ) -> bool:
        grasp = self.get_grasp(instance_id, grasp_id)
        if grasp is None:
            return False
        if quality is not None:
            grasp.quality = quality
        if difficulty is not None:
            grasp.difficulty = difficulty
        if note is not None:
            grasp.note = note
        self.dirty = True
        self.annotation_modified.emit()
        return True

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get_object_by_instance(self, instance_id: int) -> Optional[ObjectAnnotation]:
        for obj in self.objects:
            if obj.instance_id == instance_id:
                return obj
        return None

    def get_grasp(self, instance_id: int, grasp_id: int) -> Optional[GraspAnnotation]:
        obj = self.get_object_by_instance(instance_id)
        if obj is None:
            return None
        for g in obj.grasps:
            if g.grasp_id == grasp_id:
                return g
        return None

    def find_object_at(self, x: float, y: float) -> Optional[ObjectAnnotation]:
        for obj in reversed(self.objects):
            if point_in_bbox(x, y, obj.bbox_xyxy):
                return obj
        return None

    def find_grasp_at(
        self, x: float, y: float, threshold: float = 15.0,
    ) -> tuple[Optional[ObjectAnnotation], Optional[GraspAnnotation]]:
        from assistive_grasp_annotator.tools.geometry import point_near_polygon
        for obj in reversed(self.objects):
            for grasp in reversed(obj.grasps):
                flat = grasp.flatten_points()
                if point_near_polygon(x, y, flat, threshold):
                    return (obj, grasp)
        return (None, None)

    def grasp_count(self) -> int:
        return sum(len(obj.grasps) for obj in self.objects)

    # ------------------------------------------------------------------
    # Serialization — full JSON format matching spec
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        rel_path = ""
        if self.image_path is not None:
            rel_path = str(self.image_path)
        return {
            "image_id": self.image_path.stem if self.image_path else "",
            "image_path": rel_path,
            "width": self.image_size[0] if self.image_size else 0,
            "height": self.image_size[1] if self.image_size else 0,
            "camera": self.camera,
            "source": self.source,
            "split": self.split,
            "objects": [obj.to_dict() for obj in self.objects],
        }

    @staticmethod
    def from_dict(data: dict, image_path: str | Path | None = None) -> AnnotationModel:
        image_path = Path(image_path) if image_path else None
        size = (data.get("width", 0), data.get("height", 0))
        model = AnnotationModel(
            image_path=image_path,
            image_size=size,
            camera=data.get("camera", ""),
            source=data.get("source", ""),
            split=data.get("split", "train"),
        )
        for od in data.get("objects", []):
            obj = ObjectAnnotation.from_dict(od)
            model.objects.append(obj)
            if obj.instance_id >= model._next_instance_id:
                model._next_instance_id = obj.instance_id + 1
        return model

    def save(self, filepath: str | Path):
        """Atomic JSON write: temp file → fsync → rename."""
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()
        json_str = json.dumps(data, indent=2, ensure_ascii=False)

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
            dir=str(filepath.parent), encoding="utf-8",
        )
        try:
            tmp.write(json_str)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp.close()
            os.replace(tmp.name, str(filepath))
            self.dirty = False
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)

    @staticmethod
    def load(filepath: str | Path) -> AnnotationModel:
        filepath = Path(filepath)
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return AnnotationModel.from_dict(data, image_path=filepath)

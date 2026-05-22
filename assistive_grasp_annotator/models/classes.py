"""Class registry — loads and manages the object class ontology from classes.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class ClassInfo:
    id: int
    name: str
    graspable: bool = True
    policy: str = "grasp_rect"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "graspable": self.graspable,
            "policy": self.policy,
        }

    @staticmethod
    def from_dict(data: dict) -> ClassInfo:
        return ClassInfo(
            id=data["id"],
            name=data["name"],
            graspable=data.get("graspable", True),
            policy=data.get("policy", "grasp_rect"),
        )


class ClassRegistry:
    """Manages the ontology of object classes loaded from classes.yaml."""

    def __init__(self):
        self._classes: dict[int, ClassInfo] = {}
        self._name_to_id: dict[str, int] = {}

    @staticmethod
    def from_yaml(path: str | Path) -> ClassRegistry:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"classes.yaml not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        registry = ClassRegistry()
        for item in data.get("classes", []):
            info = ClassInfo.from_dict(item)
            registry._classes[info.id] = info
            registry._name_to_id[info.name] = info.id
        return registry

    def get_class(self, class_id: int) -> Optional[ClassInfo]:
        return self._classes.get(class_id)

    def get_class_by_name(self, name: str) -> Optional[ClassInfo]:
        class_id = self._name_to_id.get(name)
        if class_id is not None:
            return self._classes.get(class_id)
        return None

    def is_graspable(self, class_id: int) -> bool:
        info = self._classes.get(class_id)
        return info.graspable if info else False

    def all_classes(self) -> list[ClassInfo]:
        return sorted(self._classes.values(), key=lambda c: c.id)

    def class_count(self) -> int:
        return len(self._classes)

    def id_to_name(self, class_id: int) -> str:
        info = self._classes.get(class_id)
        return info.name if info else f"unknown_{class_id}"

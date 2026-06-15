"""Shared annotation quality rules for UI, validation, and export (YOLO-Angle)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# YOLO-Angle annotation constants
# ---------------------------------------------------------------------------

YAW_LABEL_STATUSES = {"valid", "not_required", "ambiguous", "occluded", "optional"}
OCCLUSION_LEVELS = {0, 1, 2, 3}
DIFFICULTIES = {"easy", "medium", "hard"}

# Per-class yaw requirement hints
# True = needs yaw, False = no yaw needed, None = conditional
CLASS_YAW_REQUIRED: dict[str, bool | None] = {
    "earbud": True,
    "phial": False,
    "bottle": False,
    "phone": True,
    "remote": True,
    "tissue": None,
    "apple": False,
}

@dataclass(frozen=True)
class ValidationIssue:
    severity: str       # "error" | "warning"
    code: str
    message: str
    suggestion: str = ""
    image_key: str | None = None
    instance_id: int | None = None

    def to_dict(self, image_key: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        resolved_image_key = self.image_key if self.image_key is not None else image_key
        if resolved_image_key is not None:
            payload["image_key"] = resolved_image_key
        if self.instance_id is not None:
            payload["instance_id"] = self.instance_id
        if self.suggestion:
            payload["suggestion"] = self.suggestion
        return payload

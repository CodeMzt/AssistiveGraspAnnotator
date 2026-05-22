"""Validation rules for annotation data."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from assistive_grasp_annotator.models.annotation import (
        AnnotationModel,
        GraspAnnotation,
        ObjectAnnotation,
    )
    from assistive_grasp_annotator.models.classes import ClassRegistry

ALLOWED_DIFFICULTIES = {"easy", "medium", "hard", "invalid"}


def validate_annotation(
    annotation: AnnotationModel, class_registry: ClassRegistry | None = None,
) -> list[str]:
    """Run all validation checks. Returns list of error strings (empty = valid)."""
    errors: list[str] = []

    if annotation.image_size is None or annotation.image_size[0] <= 0:
        errors.append("Image size not set or invalid")
        return errors

    img_w, img_h = annotation.image_size
    seen_ids: set[int] = set()

    for obj in annotation.objects:
        if obj.instance_id in seen_ids:
            errors.append(f"Object {obj.instance_id}: duplicate instance_id")
        seen_ids.add(obj.instance_id)
        errors.extend(_validate_object(obj, annotation, class_registry, img_w, img_h))

    return errors


def _validate_object(
    obj: ObjectAnnotation,
    annotation: AnnotationModel,
    class_registry: ClassRegistry | None,
    img_w: int,
    img_h: int,
) -> list[str]:
    errors: list[str] = []
    oid = f"Object {obj.instance_id}"

    bbox = obj.bbox_xyxy
    if len(bbox) != 4:
        errors.append(f"{oid}: bbox must have 4 values")
        return errors

    x1, y1, x2, y2 = bbox

    if x1 >= x2:
        errors.append(f"{oid}: bbox x1 ({x1}) >= x2 ({x2})")
    if y1 >= y2:
        errors.append(f"{oid}: bbox y1 ({y1}) >= y2 ({y2})")
    if x2 - x1 <= 0 or y2 - y1 <= 0:
        errors.append(f"{oid}: bbox area is zero")

    if x1 < 0 or y1 < 0 or x2 > img_w or y2 > img_h:
        errors.append(f"{oid}: bbox exceeds image bounds ({img_w}x{img_h})")

    if class_registry is not None:
        if class_registry.get_class(obj.class_id) is None:
            errors.append(f"{oid}: unknown class_id {obj.class_id}")

    if not obj.graspable and len(obj.grasps) > 0:
        errors.append(f"{oid}: non-graspable class has grasps (WARNING)")

    for grasp in obj.grasps:
        errors.extend(_validate_grasp(grasp, obj, img_w, img_h))

    return errors


def _validate_grasp(
    grasp: GraspAnnotation, obj: ObjectAnnotation, img_w: int, img_h: int,
) -> list[str]:
    errors: list[str] = []
    gid = f"Object {obj.instance_id} Grasp {grasp.grasp_id}"

    pts = grasp.points
    if len(pts) != 4:
        errors.append(f"{gid}: need 4 points, got {len(pts)}")
        return errors

    width_val = _dist(pts[0], pts[1])
    if width_val <= 0:
        errors.append(f"{gid}: width must be > 0")
    depth_val = _dist(pts[1], pts[2])
    if depth_val <= 0:
        errors.append(f"{gid}: depth must be > 0")

    for i, p in enumerate(pts):
        if not (0 <= p[0] <= img_w and 0 <= p[1] <= img_h):
            errors.append(f"{gid}: point {i} ({p[0]:.1f}, {p[1]:.1f}) outside image ({img_w}x{img_h})")

    if grasp.difficulty not in ALLOWED_DIFFICULTIES:
        errors.append(f"{gid}: invalid difficulty '{grasp.difficulty}'")

    if not (0.0 <= grasp.quality <= 1.0):
        errors.append(f"{gid}: quality {grasp.quality} out of range [0, 1]")

    return errors


def _dist(a: list[float], b: list[float]) -> float:
    import math
    return math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)

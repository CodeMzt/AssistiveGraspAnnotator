"""Pure geometry functions — no Qt imports. All coordinates in image pixel space."""

from __future__ import annotations

import math
from typing import Sequence


# ---------------------------------------------------------------------------
# Point / vector utilities
# ---------------------------------------------------------------------------

def vec2d(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float]:
    return (x2 - x1, y2 - y1)


def dot(v1: tuple[float, float], v2: tuple[float, float]) -> float:
    return v1[0] * v2[0] + v1[1] * v2[1]


def cross(v1: tuple[float, float], v2: tuple[float, float]) -> float:
    return v1[0] * v2[1] - v1[1] * v2[0]


def magnitude(v: tuple[float, float]) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1])


def normalize(v: tuple[float, float]) -> tuple[float, float]:
    mag = magnitude(v)
    if mag < 1e-9:
        return (1.0, 0.0)
    return (v[0] / mag, v[1] / mag)


def point_point_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return magnitude((x2 - x1, y2 - y1))


# ---------------------------------------------------------------------------
# Grasp rectangle operations
#
# Convention:
#   p0 -> p1 = grasp_width_axis  (gripper open/close direction)
#   p1 -> p2 = finger_depth_axis (finger insertion depth)
#   p3 = p0 + (p2 - p1)          (parallelogram)
# ---------------------------------------------------------------------------

Point2f = tuple[float, float]
GraspPoints = list[Point2f]  # len=4


def compute_p3(p0: Point2f, p1: Point2f, p2: Point2f) -> Point2f:
    """p3 = p0 + (p2 - p1). Maintains parallelogram shape."""
    return (p0[0] + p2[0] - p1[0], p0[1] + p2[1] - p1[1])


def grasp_center(points: Sequence[Point2f]) -> Point2f:
    """Centroid of the 4 grasp points."""
    n = len(points)
    if n == 0:
        return (0.0, 0.0)
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    return (sx / n, sy / n)


def grasp_width(points: Sequence[Point2f]) -> float:
    """Distance p0 -> p1."""
    return point_point_distance(points[0][0], points[0][1], points[1][0], points[1][1])


def grasp_depth(points: Sequence[Point2f]) -> float:
    """Distance p1 -> p2."""
    return point_point_distance(points[1][0], points[1][1], points[2][0], points[2][1])


def grasp_angle(points: Sequence[Point2f]) -> float:
    """Angle of width axis (p0->p1) in radians from positive x-axis."""
    return math.atan2(points[1][1] - points[0][1], points[1][0] - points[0][0])


def rotate_grasp(
    points: GraspPoints,
    angle_rad: float,
    center: Point2f | None = None,
) -> GraspPoints:
    """Rotate all 4 points around center (default: grasp_center)."""
    if center is None:
        center = grasp_center(points)
    cx, cy = center
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    result: GraspPoints = []
    for px, py in points:
        dx = px - cx
        dy = py - cy
        rx = cos_a * dx - sin_a * dy + cx
        ry = sin_a * dx + cos_a * dy + cy
        result.append((rx, ry))
    return result


def resize_grasp_width(points: GraspPoints, new_width: float) -> GraspPoints:
    """Scale width dimension about the center of the width axis."""
    cur = grasp_width(points)
    if cur < 1e-6:
        return [p for p in points]
    ratio = new_width / cur
    center = grasp_center(points)
    cx, cy = center
    result: GraspPoints = []
    for px, py in points:
        rx = cx + (px - cx) * ratio
        ry = cy + (py - cy) * ratio
        result.append((rx, ry))
    return result


def resize_grasp_depth(points: GraspPoints, new_depth: float) -> GraspPoints:
    """Scale depth dimension about the center of the depth axis."""
    # Decompose: scale along the depth direction (p1->p2) perpendicular to width
    cur = grasp_depth(points)
    if cur < 1e-6:
        return [p for p in points]
    ratio = new_depth / cur
    center = grasp_center(points)
    p0, p1 = points[0], points[1]
    width_dir = normalize((p1[0] - p0[0], p1[1] - p0[1]))
    depth_dir = (-width_dir[1], width_dir[0])
    cx, cy = center
    result: GraspPoints = []
    for px, py in points:
        dx = px - cx
        dy = py - cy
        proj_depth = dx * depth_dir[0] + dy * depth_dir[1]
        proj_width = dx * width_dir[0] + dy * width_dir[1]
        rx = cx + proj_width * width_dir[0] + proj_depth * depth_dir[0] * ratio
        ry = cy + proj_width * width_dir[1] + proj_depth * depth_dir[1] * ratio
        result.append((rx, ry))
    return result


def move_grasp(points: GraspPoints, dx: float, dy: float) -> GraspPoints:
    return [(p[0] + dx, p[1] + dy) for p in points]


# ---------------------------------------------------------------------------
# Bounding box operations
# bbox format: [x1, y1, x2, y2] (x1 < x2, y1 < y2)
# ---------------------------------------------------------------------------

Bbox = list[float]  # [x1, y1, x2, y2]


def bbox_center(bbox: Sequence[float]) -> Point2f:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def bbox_width(bbox: Sequence[float]) -> float:
    return bbox[2] - bbox[0]


def bbox_height(bbox: Sequence[float]) -> float:
    return bbox[3] - bbox[1]


def bbox_area(bbox: Sequence[float]) -> float:
    return bbox_width(bbox) * bbox_height(bbox)


def point_in_bbox(px: float, py: float, bbox: Sequence[float]) -> bool:
    return bbox[0] <= px <= bbox[2] and bbox[1] <= py <= bbox[3]


def extend_bbox(
    bbox: Sequence[float],
    padding_ratio: float = 0.2,
    clamp_width: float | None = None,
    clamp_height: float | None = None,
) -> Bbox:
    """Extend bbox by padding_ratio on each side, optionally clamped."""
    w = bbox_width(bbox)
    h = bbox_height(bbox)
    pad_w = w * padding_ratio
    pad_h = h * padding_ratio
    x1 = bbox[0] - pad_w
    y1 = bbox[1] - pad_h
    x2 = bbox[2] + pad_w
    y2 = bbox[3] + pad_h
    if clamp_width is not None:
        x1 = max(0.0, x1)
        x2 = min(clamp_width, x2)
    if clamp_height is not None:
        y1 = max(0.0, y1)
        y2 = min(clamp_height, y2)
    return [x1, y1, x2, y2]


# ---------------------------------------------------------------------------
# Coordinate transforms
# ---------------------------------------------------------------------------

def normalize_bbox(
    bbox: Sequence[float], img_w: int, img_h: int
) -> tuple[float, float, float, float]:
    """Convert [x1,y1,x2,y2] to YOLO format (cx_norm, cy_norm, w_norm, h_norm)."""
    cx = (bbox[0] + bbox[2]) / 2.0 / img_w
    cy = (bbox[1] + bbox[3]) / 2.0 / img_h
    bw = (bbox[2] - bbox[0]) / img_w
    bh = (bbox[3] - bbox[1]) / img_h
    return (cx, cy, bw, bh)


def denormalize_bbox(
    cx_norm: float, cy_norm: float, w_norm: float, h_norm: float,
    img_w: int, img_h: int,
) -> Bbox:
    half_w = w_norm * img_w / 2.0
    half_h = h_norm * img_h / 2.0
    cx = cx_norm * img_w
    cy = cy_norm * img_h
    return [cx - half_w, cy - half_h, cx + half_w, cy + half_h]


def transform_to_roi(
    points: list[Point2f], roi_bbox: Sequence[float]
) -> list[Point2f]:
    """Transform points from image coordinates to ROI-local coordinates."""
    ox, oy = roi_bbox[0], roi_bbox[1]
    return [(p[0] - ox, p[1] - oy) for p in points]


# ---------------------------------------------------------------------------
# Point-in-polygon (ray casting)
# ---------------------------------------------------------------------------

def point_in_polygon(px: float, py: float, polygon: Sequence[Point2f]) -> bool:
    """Ray casting: count edge crossings along positive x-axis."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def point_near_polygon(
    px: float, py: float, polygon: Sequence[Point2f], threshold: float = 15.0
) -> bool:
    """True if point is inside polygon or within threshold of any edge."""
    if point_in_polygon(px, py, polygon):
        return True
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if point_segment_distance(px, py, x1, y1, x2, y2) <= threshold:
            return True
    return False


def point_segment_distance(
    px: float, py: float, x1: float, y1: float, x2: float, y2: float
) -> float:
    """Minimum distance from point (px,py) to segment (x1,y1)-(x2,y2)."""
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return point_point_distance(px, py, x1, y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return point_point_distance(px, py, proj_x, proj_y)


def closest_point_on_segment(
    px: float, py: float, x1: float, y1: float, x2: float, y2: float
) -> tuple[float, float]:
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return (x1, y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return (x1 + t * dx, y1 + t * dy)


def rasterize_polygon(
    polygon: Sequence[Point2f], h: int, w: int
) -> list[tuple[int, int]]:
    """Return list of (row, col) pixel indices inside the polygon.

    Tests each pixel center (col+0.5, row+0.5) against the polygon.
    Suitable for small-to-medium map sizes (e.g. 320×240).
    """
    pixels: list[tuple[int, int]] = []
    for row in range(h):
        for col in range(w):
            if point_in_polygon(col + 0.5, row + 0.5, polygon):
                pixels.append((row, col))
    return pixels


def compute_compact_polygon(
    points: Sequence[Point2f], factor: float = 1.0 / 3.0
) -> GraspPoints:
    """Shrink grasp rectangle to its center portion along both axes.

    points: [p0, p1, p2, p3] where p0→p1=width, p1→p2=depth.
    factor: fraction of original size to keep (GG-CNN uses 1/3).

    Returns 4-point polygon of the shrunken center region.
    """
    if len(points) < 4:
        return list(points)

    p0, p1, p2 = points[0], points[1], points[2]
    center = grasp_center(points)
    g_width = grasp_width(points)
    g_depth = grasp_depth(points)

    if g_width < 1e-6 or g_depth < 1e-6:
        return [center, center, center, center]

    w_dir = normalize((p1[0] - p0[0], p1[1] - p0[1]))
    d_dir = normalize((p2[0] - p1[0], p2[1] - p1[1]))

    half_w = g_width * 0.5 * factor
    half_d = g_depth * 0.5 * factor
    cx, cy = center

    return [
        (cx - w_dir[0] * half_w - d_dir[0] * half_d,
         cy - w_dir[1] * half_w - d_dir[1] * half_d),
        (cx + w_dir[0] * half_w - d_dir[0] * half_d,
         cy + w_dir[1] * half_w - d_dir[1] * half_d),
        (cx + w_dir[0] * half_w + d_dir[0] * half_d,
         cy + w_dir[1] * half_w + d_dir[1] * half_d),
        (cx - w_dir[0] * half_w + d_dir[0] * half_d,
         cy - w_dir[1] * half_w + d_dir[1] * half_d),
    ]

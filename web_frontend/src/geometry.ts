import type { Annotation, CanvasHandle, CanvasSelection, GraspAnnotation, ObjectAnnotation, Point } from "./types";

export function computeP3(p0: Point, p1: Point, p2: Point): Point {
  return [p0[0] + p2[0] - p1[0], p0[1] + p2[1] - p1[1]];
}

export function normalizeBbox(a: Point, b: Point): [number, number, number, number] {
  return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
}

export function clampPoint(point: Point, annotation: Annotation | null): Point {
  if (!annotation) return point;
  return [
    Math.max(0, Math.min(annotation.width, point[0])),
    Math.max(0, Math.min(annotation.height, point[1]))
  ];
}

export function pointDistance(a: Point, b: Point) {
  return Math.hypot(b[0] - a[0], b[1] - a[1]);
}

export function movePoints(points: Point[], dx: number, dy: number): Point[] {
  return points.map((point) => [point[0] + dx, point[1] + dy]);
}

export function centerOf(points: Point[]): Point {
  return [
    points.reduce((sum, point) => sum + point[0], 0) / points.length,
    points.reduce((sum, point) => sum + point[1], 0) / points.length
  ];
}

export function rotatePoints(points: Point[], angle: number, center = centerOf(points)): Point[] {
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return points.map((point) => {
    const dx = point[0] - center[0];
    const dy = point[1] - center[1];
    return [center[0] + dx * cos - dy * sin, center[1] + dx * sin + dy * cos];
  });
}

export function pointInBbox(point: Point, bbox: [number, number, number, number]) {
  return point[0] >= bbox[0] && point[0] <= bbox[2] && point[1] >= bbox[1] && point[1] <= bbox[3];
}

function distToSegment(point: Point, a: Point, b: Point) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  if (dx === 0 && dy === 0) return pointDistance(point, a);
  const t = Math.max(0, Math.min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / (dx * dx + dy * dy)));
  return pointDistance(point, [a[0] + t * dx, a[1] + t * dy]);
}

function pointInPolygon(point: Point, polygon: Point[]) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i][0];
    const yi = polygon[i][1];
    const xj = polygon[j][0];
    const yj = polygon[j][1];
    const intersects = yi > point[1] !== yj > point[1] && point[0] < ((xj - xi) * (point[1] - yi)) / (yj - yi + 1e-9) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}

function pointNearPolygon(point: Point, polygon: Point[], threshold: number) {
  if (pointInPolygon(point, polygon)) return true;
  for (let i = 0; i < polygon.length; i += 1) {
    if (distToSegment(point, polygon[i], polygon[(i + 1) % polygon.length]) <= threshold) return true;
  }
  return false;
}

function bboxHandle(point: Point, obj: ObjectAnnotation, threshold: number): CanvasHandle {
  const [x1, y1, x2, y2] = obj.bbox_xyxy;
  const handles: [CanvasHandle, Point][] = [
    ["nw", [x1, y1]],
    ["ne", [x2, y1]],
    ["sw", [x1, y2]],
    ["se", [x2, y2]]
  ];
  for (const [handle, handlePoint] of handles) {
    if (pointDistance(point, handlePoint) <= threshold) return handle;
  }
  return pointInBbox(point, obj.bbox_xyxy) ? "body" : null;
}

function rotateHandlePoint(grasp: GraspAnnotation): Point {
  const center = centerOf(grasp.points);
  return [center[0], center[1] - 30];
}

function graspHandle(point: Point, grasp: GraspAnnotation, threshold: number): CanvasHandle {
  for (let index = 0; index < grasp.points.length; index += 1) {
    if (pointDistance(point, grasp.points[index]) <= threshold) return `p${index}` as CanvasHandle;
  }
  if (pointDistance(point, rotateHandlePoint(grasp)) <= threshold) return "rotate";
  return pointNearPolygon(point, grasp.points, threshold) ? "body" : null;
}

export function hitTest(annotation: Annotation, point: Point, threshold = 12): CanvasSelection {
  for (let oi = annotation.objects.length - 1; oi >= 0; oi -= 1) {
    const obj = annotation.objects[oi];
    for (let gi = obj.grasps.length - 1; gi >= 0; gi -= 1) {
      const grasp = obj.grasps[gi];
      const handle = graspHandle(point, grasp, threshold);
      if (handle) return { objectId: obj.instance_id, graspId: grasp.grasp_id, handle };
    }
  }
  for (let oi = annotation.objects.length - 1; oi >= 0; oi -= 1) {
    const obj = annotation.objects[oi];
    const handle = bboxHandle(point, obj, threshold);
    if (handle) return { objectId: obj.instance_id, graspId: null, handle };
  }
  return { objectId: null, graspId: null, handle: null };
}

export function findObjectAt(annotation: Annotation, point: Point): ObjectAnnotation | null {
  for (let index = annotation.objects.length - 1; index >= 0; index -= 1) {
    if (pointInBbox(point, annotation.objects[index].bbox_xyxy)) return annotation.objects[index];
  }
  return null;
}

export function derivedRotateHandle(grasp: GraspAnnotation): Point {
  return rotateHandlePoint(grasp);
}


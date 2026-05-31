import type {
  Annotation,
  AnnotationAction,
  ClassInfo,
  GraspAnnotation,
  ObjectAnnotation,
  Point
} from "./types";
import { computeP3, movePoints, rotatePoints } from "./geometry";

export function qualityForDifficulty(difficulty: GraspAnnotation["difficulty"]) {
  return difficulty === "easy" ? 1.0 : difficulty === "medium" ? 0.7 : difficulty === "hard" ? 0.4 : 0.0;
}

export function firstClass(classes: ClassInfo[]): ClassInfo {
  return classes[0] || { id: 0, name: "", graspable: true, policy: "grasp_rect" };
}

function nextObjectId(annotation: Annotation) {
  return Math.max(0, ...annotation.objects.map((obj) => obj.instance_id)) + 1;
}

function nextGraspId(obj: ObjectAnnotation) {
  return Math.max(0, ...obj.grasps.map((grasp) => grasp.grasp_id)) + 1;
}

function withObject(annotation: Annotation, instanceId: number, updater: (obj: ObjectAnnotation) => ObjectAnnotation) {
  return {
    ...annotation,
    objects: annotation.objects.map((obj) => (obj.instance_id === instanceId ? updater(obj) : obj))
  };
}

function withGrasp(
  annotation: Annotation,
  instanceId: number,
  graspId: number,
  updater: (grasp: GraspAnnotation) => GraspAnnotation
) {
  return withObject(annotation, instanceId, (obj) => ({
    ...obj,
    grasps: obj.grasps.map((grasp) => (grasp.grasp_id === graspId ? updater(grasp) : grasp))
  }));
}

function compactInstanceIds(objects: ObjectAnnotation[]) {
  return objects.map((obj, index) => ({ ...obj, instance_id: index + 1 }));
}

function normalizeGraspPoints(points: Point[]): Point[] {
  if (points.length === 3) {
    return [points[0], points[1], points[2], computeP3(points[0], points[1], points[2])];
  }
  if (points.length >= 4) {
    return [points[0], points[1], points[2], computeP3(points[0], points[1], points[2])];
  }
  return points;
}

export function annotationReducer(annotation: Annotation, action: AnnotationAction): Annotation {
  switch (action.type) {
    case "addObject": {
      const instanceId = nextObjectId(annotation);
      return {
        ...annotation,
        objects: [
          ...annotation.objects,
          {
            instance_id: instanceId,
            class_id: action.classInfo.id,
            class_name: action.classInfo.name,
            bbox_xyxy: action.bbox,
            graspable: action.classInfo.graspable,
            policy: action.classInfo.policy,
            grasps: []
          }
        ]
      };
    }
    case "deleteObject":
      return {
        ...annotation,
        objects: compactInstanceIds(annotation.objects.filter((obj) => obj.instance_id !== action.instanceId))
      };
    case "updateObjectBbox":
      return withObject(annotation, action.instanceId, (obj) => ({ ...obj, bbox_xyxy: action.bbox }));
    case "moveObject":
      return withObject(annotation, action.instanceId, (obj) => {
        const [x1, y1, x2, y2] = obj.bbox_xyxy;
        return { ...obj, bbox_xyxy: [x1 + action.dx, y1 + action.dy, x2 + action.dx, y2 + action.dy] };
      });
    case "updateObjectClass":
      return withObject(annotation, action.instanceId, (obj) => ({
        ...obj,
        class_id: action.classInfo.id,
        class_name: action.classInfo.name,
        graspable: action.classInfo.graspable,
        policy: action.classInfo.policy
      }));
    case "addGrasp":
      return withObject(annotation, action.instanceId, (obj) => ({
        ...obj,
        grasps: [
          ...obj.grasps,
          {
            grasp_id: nextGraspId(obj),
            points: normalizeGraspPoints(action.points),
            axis_convention: "p0_to_p1_is_grasp_width_axis",
            quality: 1.0,
            difficulty: "easy",
            note: ""
          }
        ]
      }));
    case "deleteGrasp":
      return withObject(annotation, action.instanceId, (obj) => ({
        ...obj,
        grasps: obj.grasps.filter((grasp) => grasp.grasp_id !== action.graspId)
      }));
    case "moveGrasp":
      return withGrasp(annotation, action.instanceId, action.graspId, (grasp) => ({
        ...grasp,
        points: movePoints(grasp.points, action.dx, action.dy)
      }));
    case "rotateGrasp":
      return withGrasp(annotation, action.instanceId, action.graspId, (grasp) => ({
        ...grasp,
        points: rotatePoints(grasp.points, action.angle)
      }));
    case "updateGraspPoint":
      return withGrasp(annotation, action.instanceId, action.graspId, (grasp) => {
        if (action.pointIndex === 3) return grasp;
        const next = grasp.points.map((point, index) => (index === action.pointIndex ? action.point : point));
        return { ...grasp, points: normalizeGraspPoints(next) };
      });
    case "updateGraspMetadata":
      return withGrasp(annotation, action.instanceId, action.graspId, (grasp) => {
        const difficulty = action.difficulty ?? grasp.difficulty;
        return {
          ...grasp,
          difficulty,
          quality: action.quality ?? (action.difficulty ? qualityForDifficulty(difficulty) : grasp.quality),
          note: action.note ?? grasp.note
        };
      });
    default:
      return annotation;
  }
}


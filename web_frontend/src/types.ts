export type Point = [number, number];

export type ClassInfo = {
  id: number;
  name: string;
  graspable: boolean;
  policy: string;
};

export type GraspAnnotation = {
  grasp_id: number;
  points: Point[];
  axis_convention: string;
  quality: number;
  difficulty: "easy" | "medium" | "hard" | "invalid";
  note: string;
};

export type ObjectAnnotation = {
  instance_id: number;
  class_id: number;
  class_name: string;
  bbox_xyxy: [number, number, number, number];
  graspable: boolean;
  policy: string;
  grasps: GraspAnnotation[];
};

export type Annotation = {
  image_id: string;
  image_path: string;
  width: number;
  height: number;
  camera: string;
  source: string;
  split: string;
  objects: ObjectAnnotation[];
};

export type LockInfo = {
  lock_id: string;
  lock_token?: string;
  dataset_id: string;
  image_id: string;
  image_key: string;
  user: string;
  expires_at: string;
};

export type ValidationMessage = {
  image_key: string;
  message: string;
};

export type ValidationResult = {
  valid: boolean;
  errors: ValidationMessage[];
  warnings: ValidationMessage[];
};

export type ImageItem = {
  image_id: string;
  image_key: string;
  status: "unannotated" | "empty" | "annotated";
  object_count: number;
  grasp_count: number;
  lock: LockInfo | null;
};

export type DatasetMeta = {
  dataset_id: string;
  name: string;
  root: string;
  source: string;
  image_count: number;
  annotated: number;
  empty: number;
  unannotated: number;
  classes: ClassInfo[];
  missing?: boolean;
};

export type AnnotationPayload = {
  annotation: Annotation;
  etag: string;
  image_id: string;
  image_key: string;
  lock: LockInfo | null;
  validation?: ValidationResult;
};

export type Mode = "select" | "bbox" | "grasp" | "pan";

export type CanvasHandle = "body" | "nw" | "ne" | "sw" | "se" | "p0" | "p1" | "p2" | "p3" | "rotate" | null;

export type CanvasSelection = {
  objectId: number | null;
  graspId: number | null;
  handle?: CanvasHandle;
};

export type CanvasTransform = {
  scale: number;
  x: number;
  y: number;
};

export type AnnotationAction =
  | { type: "addObject"; classInfo: ClassInfo; bbox: [number, number, number, number] }
  | { type: "deleteObject"; instanceId: number }
  | { type: "updateObjectBbox"; instanceId: number; bbox: [number, number, number, number] }
  | { type: "moveObject"; instanceId: number; dx: number; dy: number }
  | { type: "updateObjectClass"; instanceId: number; classInfo: ClassInfo }
  | { type: "addGrasp"; instanceId: number; points: Point[] }
  | { type: "deleteGrasp"; instanceId: number; graspId: number }
  | { type: "moveGrasp"; instanceId: number; graspId: number; dx: number; dy: number }
  | { type: "rotateGrasp"; instanceId: number; graspId: number; angle: number }
  | { type: "updateGraspPoint"; instanceId: number; graspId: number; pointIndex: number; point: Point }
  | { type: "updateGraspMetadata"; instanceId: number; graspId: number; difficulty?: GraspAnnotation["difficulty"]; quality?: number; note?: string };

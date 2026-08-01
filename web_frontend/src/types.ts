export type Point = [number, number];

export type ClassInfo = {
  id: number;
  name: string;
  graspable: boolean;
};

export type YawLabelStatus = "valid" | "not_required" | "ambiguous" | "occluded" | "optional";

export type ObjectAnnotation = {
  instance_id: number;
  class_id: number;
  class_name: string;
  bbox_xyxy: [number, number, number, number];
  graspable: boolean;
  template_id: string;
  yaw_label_status: YawLabelStatus;
  occlusion_level: 0 | 1 | 2 | 3;
  difficulty: "easy" | "medium" | "hard";
  main_axis_points: Point[] | null;
  obb_points?: Point[] | null;
  notes: string;
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
  severity?: "error" | "warning";
  code?: string;
  image_key: string;
  instance_id?: number;
  message: string;
  suggestion?: string;
};

export type ValidationResult = {
  valid: boolean;
  errors: ValidationMessage[];
  warnings: ValidationMessage[];
};

export type ImageStatus =
  | "unannotated"
  | "empty"
  | "annotated"
  | "all"
  | "legacy"
  | "yaw_review"
  | "mask_unreviewed"
  | "mask_low_score";

export type ImageItem = {
  image_id: string;
  image_key: string;
  status: "unannotated" | "empty" | "annotated";
  object_count: number;
  axis_count: number;
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

export type MaskCandidate = {
  schema_version: string;
  candidate_id: string;
  source: string;
  algorithm_version: string;
  image_id: string;
  instance_id: number;
  class_id: number;
  class_name: string;
  bbox_xyxy: [number, number, number, number];
  roi_xyxy: [number, number, number, number];
  annotation_signature: string;
  mask_origin_xy: [number, number];
  mask_size: [number, number];
  mask_png: string;
  preview_png: string;
  smooth_contour_px: Point[];
  anchor_px: Point;
  area_px: number;
  quality_auto_score: number;
  stale?: boolean;
};

export type MaskReview = {
  schema_version: string;
  candidate_id: string | null;
  instance_id: number;
  score: number;
  review_status: "accepted" | "usable" | "uncertain" | "rejected";
  failure_tags: string[];
  notes: string;
  reviewer: string;
  reviewed_at: string;
};

export type MaskReviewObject = {
  instance_id: number;
  candidate: MaskCandidate | null;
  review: MaskReview | null;
};

export type MaskReviewPayload = {
  image_id: string;
  image_key: string;
  objects: MaskReviewObject[];
};

export type Mode = "select" | "bbox" | "axis" | "mask" | "pan";

export type CanvasHandle = "body" | "nw" | "ne" | "sw" | "se" | "axis0" | "axis1" | null;

export type CanvasSelection = {
  objectId: number | null;
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
  | { type: "updateObjectYawStatus"; instanceId: number; yawLabelStatus: YawLabelStatus }
  | { type: "updateObjectOcclusion"; instanceId: number; occlusionLevel: 0 | 1 | 2 | 3 }
  | { type: "updateObjectDifficulty"; instanceId: number; difficulty: "easy" | "medium" | "hard" }
  | { type: "updateObjectMainAxis"; instanceId: number; mainAxisPoints: Point[] | null }
  | { type: "updateObjectTemplate"; instanceId: number; templateId: string }
  | { type: "updateObjectNotes"; instanceId: number; notes: string };

export type NumberSummary = {
  count: number;
  mean: number | null;
  p10: number | null;
  p50: number | null;
  p90: number | null;
};

export type ClassStats = {
  class_id: number;
  class_name: string;
  graspable: boolean;
  image_count: number;
  object_count: number;
  axis_count: number;
  yaw_valid_count: number;
  yaw_status_counts: Record<string, number>;
  occlusion_counts: Record<string, number>;
  difficulty_counts: Record<string, number>;
  obb_count: number;
  object_share: number;
  error_count: number;
  warning_count: number;
  suggestions: string[];
};

export type ImageStats = ImageItem & {
  error_count: number;
  warning_count: number;
};

export type DatasetStats = {
  dataset: {
    image_count: number;
    annotated_image_count: number;
    empty_image_count: number;
    unannotated_image_count: number;
    class_count: number;
    object_count: number;
    axis_count: number;
    error_count: number;
    warning_count: number;
  };
  classes: ClassStats[];
  images: ImageStats[];
  issues: ValidationMessage[];
};

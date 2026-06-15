import { Download, Trash2 } from "lucide-react";
import type {
  Annotation,
  CanvasSelection,
  ClassInfo,
  DatasetMeta,
  ValidationMessage,
  YawLabelStatus
} from "../types";

type Props = {
  dataset: DatasetMeta | null;
  annotation: Annotation | null;
  imageKey: string;
  selection: CanvasSelection;
  editable: boolean;
  validationErrors: ValidationMessage[];
  validationWarnings: ValidationMessage[];
  jobMessage: string;
  onSelectionChange: (selection: CanvasSelection) => void;
  onClassChange: (instanceId: number, classInfo: ClassInfo) => void;
  onYawStatusChange: (instanceId: number, status: YawLabelStatus) => void;
  onOcclusionChange: (instanceId: number, level: 0 | 1 | 2 | 3) => void;
  onDifficultyChange: (instanceId: number, difficulty: "easy" | "medium" | "hard") => void;
  onTemplateChange: (instanceId: number, templateId: string) => void;
  onNotesChange: (instanceId: number, notes: string) => void;
  onExport: (exportType: "yolo" | "yolo_angle" | "obb_teacher") => void;
  onDeleteImage: () => void;
};

const YAW_STATUS_OPTIONS: { value: YawLabelStatus; label: string }[] = [
  { value: "valid", label: "valid — 有稳定主轴" },
  { value: "not_required", label: "not_required — 不需要朝向" },
  { value: "ambiguous", label: "ambiguous — 方向不唯一" },
  { value: "occluded", label: "occluded — 遮挡严重" },
  { value: "optional", label: "optional — 可选/不参与" },
];

const OCCLUSION_OPTIONS: { value: 0 | 1 | 2 | 3; label: string }[] = [
  { value: 0, label: "0 — 无遮挡" },
  { value: 1, label: "1 — 轻微" },
  { value: 2, label: "2 — 中等" },
  { value: 3, label: "3 — 严重" },
];

const DIFFICULTY_OPTIONS: { value: "easy" | "medium" | "hard"; label: string }[] = [
  { value: "easy", label: "easy" },
  { value: "medium", label: "medium" },
  { value: "hard", label: "hard" },
];

export function SidePanel({
  dataset,
  annotation,
  imageKey,
  selection,
  editable,
  validationErrors,
  validationWarnings,
  jobMessage,
  onSelectionChange,
  onClassChange,
  onYawStatusChange,
  onOcclusionChange,
  onDifficultyChange,
  onTemplateChange,
  onNotesChange,
  onExport,
  onDeleteImage
}: Props) {
  const selectedObject = annotation?.objects.find((obj) => obj.instance_id === selection.objectId) || null;
  const axisCount = annotation ? annotation.objects.filter((obj) => obj.main_axis_points && obj.main_axis_points.length === 2).length : 0;
  const issueLabel = (item: ValidationMessage) => {
    const parts = [item.image_key || imageKey || ""];
    if (item.instance_id != null) parts.push(`obj ${item.instance_id}`);
    if (item.code) parts.push(item.code);
    return parts.filter(Boolean).join(" / ");
  };

  return (
    <aside className="right-panel">
      <section>
        <div className="section-title">Image Info</div>
        <dl className="info-grid">
          <dt>Path</dt>
          <dd>{imageKey || ""}</dd>
          <dt>Size</dt>
          <dd>{annotation ? `${annotation.width} x ${annotation.height}` : ""}</dd>
          <dt>Objects</dt>
          <dd>{annotation ? `${annotation.objects.length} objects, ${axisCount} with axis` : ""}</dd>
        </dl>
        {imageKey && (
          <button className="danger-button small" onClick={onDeleteImage} title="Delete this image">
            <Trash2 size={14} /> Delete Image
          </button>
        )}
      </section>

      <section>
        <div className="section-title">Objects</div>
        <div className="object-list">
          {annotation?.objects.map((obj) => (
            <button
              key={obj.instance_id}
              className={selection.objectId === obj.instance_id && !selection.handle?.startsWith("axis") ? "object-row active" : "object-row"}
              onClick={() => onSelectionChange({ objectId: obj.instance_id, handle: null })}
            >
              <span>[{obj.instance_id}] {obj.class_name || `class_${obj.class_id}`}</span>
              <em>{!obj.graspable ? "r/o" : obj.yaw_label_status === "valid" ? "yaw✓" : obj.yaw_label_status}</em>
            </button>
          ))}
        </div>
        {selectedObject && (
          <>
            <label>Class</label>
            <select
              disabled={!editable}
              value={selectedObject.class_id}
              onChange={(event) => {
                const cls = dataset?.classes.find((item) => item.id === Number(event.target.value));
                if (cls) onClassChange(selectedObject.instance_id, cls);
              }}
            >
              {dataset?.classes.map((cls) => (
                <option key={cls.id} value={cls.id}>
                  {cls.name} (id={cls.id})
                </option>
              ))}
            </select>
            <div className="bbox-readout">
              {selectedObject.bbox_xyxy.map((value, index) => (
                <span key={index}>{value.toFixed(1)}</span>
              ))}
            </div>
            <div className="class-chip-grid">
              {dataset?.classes.map((cls) => (
                <button
                  key={cls.id}
                  disabled={!editable}
                  className={selectedObject.class_id === cls.id ? "class-chip active" : "class-chip"}
                  onClick={() => onClassChange(selectedObject.instance_id, cls)}
                >
                  {cls.name}
                </button>
              ))}
            </div>
          </>
        )}
      </section>

      {selectedObject && (
        <section>
          <div className="section-title">YOLO-Angle Properties</div>

          <label>Yaw Label Status</label>
          <select
            disabled={!editable}
            value={selectedObject.yaw_label_status}
            onChange={(event) => onYawStatusChange(selectedObject.instance_id, event.target.value as YawLabelStatus)}
          >
            {YAW_STATUS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>

          <label>Occlusion Level</label>
          <select
            disabled={!editable}
            value={selectedObject.occlusion_level}
            onChange={(event) => onOcclusionChange(selectedObject.instance_id, Number(event.target.value) as 0 | 1 | 2 | 3)}
          >
            {OCCLUSION_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>

          <label>Difficulty</label>
          <select
            disabled={!editable}
            value={selectedObject.difficulty}
            onChange={(event) => onDifficultyChange(selectedObject.instance_id, event.target.value as "easy" | "medium" | "hard")}
          >
            {DIFFICULTY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>

          <label>Template ID</label>
          <input
            disabled={!editable}
            value={selectedObject.template_id}
            onChange={(event) => onTemplateChange(selectedObject.instance_id, event.target.value)}
            placeholder="e.g. phial"
          />

          <label>Main Axis Points {selectedObject.main_axis_points && selectedObject.main_axis_points.length === 2 ? "(set)" : "(not set — use E key in canvas)"}</label>
          {selectedObject.main_axis_points && selectedObject.main_axis_points.length === 2 && (
            <div className="bbox-readout">
              <span>p0: [{selectedObject.main_axis_points[0][0].toFixed(0)}, {selectedObject.main_axis_points[0][1].toFixed(0)}]</span>
              <span>p1: [{selectedObject.main_axis_points[1][0].toFixed(0)}, {selectedObject.main_axis_points[1][1].toFixed(0)}]</span>
            </div>
          )}

          <label>Notes</label>
          <textarea
            disabled={!editable}
            value={selectedObject.notes}
            onChange={(event) => onNotesChange(selectedObject.instance_id, event.target.value)}
            rows={3}
            placeholder="e.g. partially occluded, edge case"
          />
        </section>
      )}

      <section>
        <div className="section-title">Export</div>
        <div className="export-buttons">
          <button disabled={!dataset} onClick={() => onExport("yolo")}>
            <Download size={16} /> YOLO Detection
          </button>
          <button disabled={!dataset} onClick={() => onExport("yolo_angle")}>
            <Download size={16} /> YOLO-Angle
          </button>
          <button disabled={!dataset} onClick={() => onExport("obb_teacher")}>
            <Download size={16} /> OBB Teacher
          </button>
        </div>
        {jobMessage && <p className="job-line">{jobMessage}</p>}
      </section>

      {(validationErrors.length > 0 || validationWarnings.length > 0) && (
        <section>
          <div className="section-title">Validation</div>
          <div className="validation-list">
            {validationErrors.map((item, index) => (
              <p className="validation-error" key={`e-${index}`}>
                <strong>{issueLabel(item)}</strong>
                <span>{item.message}</span>
                {item.suggestion && <em>{item.suggestion}</em>}
              </p>
            ))}
            {validationWarnings.map((item, index) => (
              <p className="validation-warning" key={`w-${index}`}>
                <strong>{issueLabel(item)}</strong>
                <span>{item.message}</span>
                {item.suggestion && <em>{item.suggestion}</em>}
              </p>
            ))}
          </div>
        </section>
      )}
    </aside>
  );
}

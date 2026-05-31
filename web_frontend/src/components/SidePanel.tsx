import { Download } from "lucide-react";
import type {
  Annotation,
  CanvasSelection,
  ClassInfo,
  DatasetMeta,
  GraspAnnotation,
  ValidationMessage
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
  onDifficultyChange: (instanceId: number, graspId: number, difficulty: GraspAnnotation["difficulty"]) => void;
  onQualityChange: (instanceId: number, graspId: number, quality: number) => void;
  onNoteChange: (instanceId: number, graspId: number, note: string) => void;
  onExport: (exportType: "yolo" | "grasp_roi" | "target_maps") => void;
};

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
  onDifficultyChange,
  onQualityChange,
  onNoteChange,
  onExport
}: Props) {
  const selectedObject = annotation?.objects.find((obj) => obj.instance_id === selection.objectId) || null;
  const selectedGrasp = selectedObject?.grasps.find((grasp) => grasp.grasp_id === selection.graspId) || null;

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
          <dd>{annotation ? `${annotation.objects.length} objects, ${annotation.objects.reduce((sum, obj) => sum + obj.grasps.length, 0)} grasps` : ""}</dd>
        </dl>
      </section>

      <section>
        <div className="section-title">Objects</div>
        <div className="object-list">
          {annotation?.objects.map((obj) => (
            <button
              key={obj.instance_id}
              className={selection.objectId === obj.instance_id && !selection.graspId ? "object-row active" : "object-row"}
              onClick={() => onSelectionChange({ objectId: obj.instance_id, graspId: null, handle: null })}
            >
              <span>[{obj.instance_id}] {obj.class_name || `class_${obj.class_id}`}</span>
              <em>{!obj.graspable ? "r/o" : obj.grasps.length ? `+${obj.grasps.length}g` : ""}</em>
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
                  title={`${cls.name} / ${cls.policy}`}
                >
                  {cls.name}
                </button>
              ))}
            </div>
          </>
        )}
      </section>

      <section>
        <div className="section-title">Grasps</div>
        <div className="grasp-list">
          {selectedObject?.grasps.map((grasp) => (
            <button
              key={grasp.grasp_id}
              className={selection.graspId === grasp.grasp_id ? "grasp-row active" : "grasp-row"}
              onClick={() => onSelectionChange({ objectId: selectedObject.instance_id, graspId: grasp.grasp_id, handle: null })}
            >
              <span>[G{grasp.grasp_id}] {grasp.difficulty} q={grasp.quality.toFixed(1)}</span>
              <em>{grasp.note ? grasp.note.slice(0, 20) : ""}</em>
            </button>
          ))}
        </div>
        {selectedObject && selectedGrasp && (
          <>
            <label>Difficulty</label>
            <select
              disabled={!editable}
              value={selectedGrasp.difficulty}
              onChange={(event) =>
                onDifficultyChange(selectedObject.instance_id, selectedGrasp.grasp_id, event.target.value as GraspAnnotation["difficulty"])
              }
            >
              <option value="easy">easy (1.0)</option>
              <option value="medium">medium (0.7)</option>
              <option value="hard">hard (0.4)</option>
              <option value="invalid">invalid (0.0)</option>
            </select>
            <label>Quality</label>
            <input
              disabled={!editable}
              type="number"
              min="0"
              max="1"
              step="0.05"
              value={selectedGrasp.quality}
              onChange={(event) => onQualityChange(selectedObject.instance_id, selectedGrasp.grasp_id, Number(event.target.value))}
            />
            <label>Note</label>
            <textarea
              disabled={!editable}
              value={selectedGrasp.note}
              onChange={(event) => onNoteChange(selectedObject.instance_id, selectedGrasp.grasp_id, event.target.value)}
              rows={3}
              placeholder="e.g. middle cross grasp"
            />
          </>
        )}
      </section>

      <section>
        <div className="section-title">Export</div>
        <div className="export-buttons">
          <button disabled={!dataset} onClick={() => onExport("yolo")}>
            <Download size={16} /> YOLO Labels
          </button>
          <button disabled={!dataset} onClick={() => onExport("grasp_roi")}>
            <Download size={16} /> Grasp ROIs
          </button>
          <button disabled={!dataset} onClick={() => onExport("target_maps")}>
            <Download size={16} /> Target Maps
          </button>
        </div>
        {jobMessage && <p className="job-line">{jobMessage}</p>}
      </section>

      {(validationErrors.length > 0 || validationWarnings.length > 0) && (
        <section>
          <div className="section-title">Validation</div>
          <div className="validation-list">
            {validationErrors.map((item, index) => (
              <p className="validation-error" key={`e-${index}`}>{item.image_key}: {item.message}</p>
            ))}
            {validationWarnings.map((item, index) => (
              <p className="validation-warning" key={`w-${index}`}>{item.image_key}: {item.message}</p>
            ))}
          </div>
        </section>
      )}
    </aside>
  );
}

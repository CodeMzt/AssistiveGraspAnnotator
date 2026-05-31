import { Plus, Save, Trash2 } from "lucide-react";
import type { ClassInfo } from "../types";

const POLICY_OPTIONS = [
  {
    value: "grasp_rect",
    label: "Require grasp rectangle",
    hint: "objects of this class should have grasp rectangles"
  },
  {
    value: "center_or_grasp_rect",
    label: "Center or grasp rectangle",
    hint: "center point is acceptable, grasp rectangle is preferred"
  },
  {
    value: "report_only",
    label: "Report only",
    hint: "detection class only, no grasp required"
  }
];

type Props = {
  classes: ClassInfo[];
  disabled?: boolean;
  onChange: (classes: ClassInfo[]) => void;
  onSave?: () => void;
  saveLabel?: string;
};

function nextId(classes: ClassInfo[]) {
  return Math.max(-1, ...classes.map((item) => Number(item.id))) + 1;
}

function updateClass(classes: ClassInfo[], index: number, patch: Partial<ClassInfo>) {
  return classes.map((item, row) => (row === index ? { ...item, ...patch } : item));
}

export function ClassEditor({ classes, disabled = false, onChange, onSave, saveLabel = "Save Classes" }: Props) {
  function addClass() {
    const id = nextId(classes);
    onChange([...classes, { id, name: `class_${id}`, graspable: true, policy: "grasp_rect" }]);
  }

  function deleteClass(index: number) {
    onChange(classes.filter((_, row) => row !== index));
  }

  function updatePolicy(index: number, policy: string) {
    onChange(updateClass(classes, index, { policy, graspable: policy === "report_only" ? false : classes[index].graspable }));
  }

  return (
    <div className="class-editor">
      <div className="class-editor-head">
        <button type="button" disabled={disabled} onClick={addClass}>
          <Plus size={16} /> Add Class
        </button>
        {onSave && (
          <button type="button" className="primary" disabled={disabled} onClick={onSave}>
            <Save size={16} /> {saveLabel}
          </button>
        )}
      </div>
      <p className="class-editor-help">
        Grasp Rule is saved as the <code>policy</code> field in <code>classes.yaml</code>. It tells validation and export whether this class needs grasp labels or is detection-only.
      </p>
      <div className="class-table">
        <div className="class-table-row class-table-header">
          <span>ID</span>
          <span>Name</span>
          <span>Graspable</span>
          <span>Grasp Rule</span>
          <span>Action</span>
        </div>
        {classes.map((cls, index) => (
          <div className="class-table-row" key={`${cls.id}-${index}`}>
            <input
              aria-label={`Class ${index + 1} id`}
              disabled={disabled}
              type="number"
              min="0"
              value={cls.id}
              onChange={(event) => onChange(updateClass(classes, index, { id: Number(event.target.value) }))}
            />
            <input
              aria-label={`Class ${index + 1} name`}
              disabled={disabled}
              value={cls.name}
              onChange={(event) => onChange(updateClass(classes, index, { name: event.target.value }))}
            />
            <label className="check-cell">
              <input
                disabled={disabled}
                type="checkbox"
                checked={cls.graspable}
                onChange={(event) => onChange(updateClass(classes, index, { graspable: event.target.checked }))}
              />
            </label>
            <select
              aria-label={`Class ${index + 1} grasp rule`}
              disabled={disabled}
              value={cls.policy}
              onChange={(event) => updatePolicy(index, event.target.value)}
            >
              {POLICY_OPTIONS.map((policy) => (
                <option key={policy.value} value={policy.value}>
                  {policy.label}
                </option>
              ))}
            </select>
            <button type="button" className="danger-button" disabled={disabled} onClick={() => deleteClass(index)}>
              <Trash2 size={15} /> Delete
            </button>
            <span className="class-policy-hint">{POLICY_OPTIONS.find((item) => item.value === cls.policy)?.hint}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

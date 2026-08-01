import { CheckCircle2, Hand, Lock, Minus, MousePointer2, Save, ScanLine, Square, Trash2, Unlock } from "lucide-react";
import type { LockInfo, Mode } from "../types";

type Props = {
  mode: Mode;
  canEdit: boolean;
  canAcquireLock: boolean;
  dirty: boolean;
  lock: LockInfo | null;
  lockedBy: string | null;
  onModeChange: (mode: Mode) => void;
  onAcquireLock: () => void;
  onReleaseLock: () => void;
  onSave: () => void;
  onDelete: () => void;
  onValidate: () => void;
};

export function Toolbar({
  mode,
  canEdit,
  canAcquireLock,
  dirty,
  lock,
  lockedBy,
  onModeChange,
  onAcquireLock,
  onReleaseLock,
  onSave,
  onDelete,
  onValidate
}: Props) {
  return (
    <header className="toolbar">
      <div className="mode-group" role="toolbar" aria-label="Mode">
        <button className={mode === "select" ? "active" : ""} title="Select (Q)" onClick={() => onModeChange("select")}>
          <MousePointer2 size={16} />
        </button>
        <button className={mode === "bbox" ? "active" : ""} title="BBox (C)" onClick={() => onModeChange("bbox")}>
          <Square size={16} />
        </button>
        <button className={mode === "axis" ? "active" : ""} title="Axis (E)" onClick={() => onModeChange("axis")}>
          <Minus size={16} />
        </button>
        <button className={mode === "mask" ? "active" : ""} title="Mask Review (M)" onClick={() => onModeChange("mask")}>
          <ScanLine size={16} />
        </button>
        <button className={mode === "pan" ? "active" : ""} title="Pan" onClick={() => onModeChange("pan")}>
          <Hand size={16} />
        </button>
      </div>
      <div className="toolbar-spacer" />
      {lockedBy && !lock && <span className="lock-text">Locked by {lockedBy}</span>}
      {lock ? (
        <button onClick={onReleaseLock}>
          <Unlock size={16} /> Release
        </button>
      ) : (
        <button disabled={!canAcquireLock} onClick={onAcquireLock}>
          <Lock size={16} /> Edit
        </button>
      )}
      <button disabled={!canEdit || !dirty} className="primary" onClick={onSave}>
        <Save size={16} /> Save
      </button>
      <button disabled={!canEdit} onClick={onDelete} title="Delete selected">
        <Trash2 size={16} />
      </button>
      <button onClick={onValidate}>
        <CheckCircle2 size={16} /> Validate
      </button>
    </header>
  );
}

import { X } from "lucide-react";
import type { ClassInfo } from "../types";
import { ClassEditor } from "./ClassEditor";

type Props = {
  title: string;
  classes: ClassInfo[];
  open: boolean;
  saveLabel?: string;
  onChange: (classes: ClassInfo[]) => void;
  onClose: () => void;
  onSave?: () => void;
};

export function ClassEditorDialog({ title, classes, open, saveLabel, onChange, onClose, onSave }: Props) {
  if (!open) return null;
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal-panel class-modal" role="dialog" aria-modal="true" aria-label={title}>
        <header className="modal-header">
          <div>
            <h2>{title}</h2>
            <p>{classes.length} classes</p>
          </div>
          <button type="button" title="Close" onClick={onClose}>
            <X size={16} />
          </button>
        </header>
        <ClassEditor classes={classes} onChange={onChange} onSave={onSave} saveLabel={saveLabel} />
      </section>
    </div>
  );
}

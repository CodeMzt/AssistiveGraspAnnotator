import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ClassInfo } from "../types";

type Props = {
  classes: ClassInfo[];
  position: { x: number; y: number };
  onPick: (cls: ClassInfo) => void;
  onCancel: () => void;
};

export function ClassPicker({ classes, position, onPick, onCancel }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const onPickRef = useRef(onPick);
  onPickRef.current = onPick;
  const onCancelRef = useRef(onCancel);
  onCancelRef.current = onCancel;
  const [adjustedPos, setAdjustedPos] = useState(position);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const rect = el.getBoundingClientRect();
    const gap = 8;
    let left = position.x;
    let top = position.y;

    if (rect.right > window.innerWidth - gap) {
      left = Math.max(gap, position.x - rect.width);
    }
    if (rect.bottom > window.innerHeight - gap) {
      top = Math.max(gap, position.y - rect.height);
    }
    if (left !== position.x || top !== position.y) {
      setAdjustedPos({ x: left, y: top });
    } else {
      setAdjustedPos(position);
    }
  }, [position]);

  const keyHandler = useCallback((event: KeyboardEvent) => {
    if (event.key === "Escape") {
      onCancelRef.current();
      return;
    }
    const digit = parseInt(event.key, 10);
    if (digit >= 1 && digit <= 9 && digit <= classes.length) {
      onPickRef.current(classes[digit - 1]);
    }
    if (event.key === "0" && classes.length >= 10) {
      onPickRef.current(classes[9]);
    }
  }, [classes.length]);

  useEffect(() => {
    window.addEventListener("keydown", keyHandler, true);
    return () => window.removeEventListener("keydown", keyHandler, true);
  }, [keyHandler]);

  return (
    <div
      ref={containerRef}
      className="class-picker-dropdown"
      style={{ left: adjustedPos.x, top: adjustedPos.y }}
    >
      <div className="class-picker-title">Pick class (Esc to skip)</div>
      {classes.map((cls, index) => (
        <button
          key={cls.id}
          className="class-picker-item"
          onClick={() => onPick(cls)}
        >
          <span className="class-picker-key">{index < 9 ? index + 1 : 0}</span>
          <span className="class-picker-name">{cls.name || `class_${cls.id}`}</span>
          <span className="class-picker-policy">{cls.graspable ? "GR" : "R/O"}</span>
        </button>
      ))}
    </div>
  );
}

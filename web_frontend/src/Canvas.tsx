import { memo, useEffect, useRef, useState } from "react";
import { Circle, Group, Image as KonvaImage, Layer, Line, Rect, Stage, Text } from "react-konva";
import type Konva from "konva";
import type {
  Annotation,
  AnnotationAction,
  CanvasHandle,
  CanvasSelection,
  CanvasTransform,
  ClassInfo,
  MaskCandidate,
  Mode,
  ObjectAnnotation,
  Point
} from "./types";
import {
  clampPoint,
  findObjectAt,
  hitTest,
  normalizeBbox,
} from "./geometry";
import { ClassPicker } from "./components/ClassPicker";

type Props = {
  imageUrl: string;
  annotation: Annotation | null;
  mode: Mode;
  editable: boolean;
  selection: CanvasSelection;
  classes: ClassInfo[];
  onSelectionChange: (selection: CanvasSelection) => void;
  onModeChange: (mode: Mode) => void;
  onAction: (action: AnnotationAction) => void;
  onNoObjectForAxis: () => void;
  defaultClassAction: (bbox: [number, number, number, number]) => AnnotationAction;
  maskCandidate?: MaskCandidate | null;
  maskPreviewUrl?: string;
  maskOverlayVisible?: boolean;
};

type DragState =
  | { kind: "pan"; start: { x: number; y: number }; original: CanvasTransform }
  | { kind: "bbox"; start: Point; current: Point }
  | { kind: "item"; start: Point; selection: CanvasSelection }
  | null;

function useHtmlImage(src: string) {
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  useEffect(() => {
    if (!src) {
      setImage(null);
      return;
    }
    const next = new window.Image();
    next.onload = () => setImage(next);
    next.src = src;
    return () => {
      next.onload = null;
    };
  }, [src]);
  return image;
}

function bboxFromHandle(obj: ObjectAnnotation, handle: CanvasHandle, point: Point): [number, number, number, number] {
  const [x1, y1, x2, y2] = obj.bbox_xyxy;
  if (handle === "nw") return normalizeBbox(point, [x2, y2]);
  if (handle === "ne") return normalizeBbox([x1, y2], point);
  if (handle === "sw") return normalizeBbox([x2, y1], point);
  return normalizeBbox([x1, y1], point);
}

function imageBounds(annotation: Annotation | null, point: Point) {
  if (!annotation) return false;
  return point[0] >= 0 && point[1] >= 0 && point[0] <= annotation.width && point[1] <= annotation.height;
}

function AnnotationCanvasInner({
  imageUrl,
  annotation,
  mode,
  editable,
  selection,
  classes,
  onSelectionChange,
  onModeChange,
  onAction,
  onNoObjectForAxis,
  defaultClassAction,
  maskCandidate = null,
  maskPreviewUrl = "",
  maskOverlayVisible = true
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<Konva.Stage | null>(null);
  const image = useHtmlImage(imageUrl);
  const maskPreview = useHtmlImage(maskPreviewUrl && maskOverlayVisible ? maskPreviewUrl : "");
  const [size, setSize] = useState({ width: 900, height: 700 });
  const [transform, setTransform] = useState<CanvasTransform>({ scale: 1, x: 0, y: 0 });
  const [drag, setDrag] = useState<DragState>(null);
  const [axisDraft, setAxisDraft] = useState<Point[]>([]);
  const [spaceHeld, setSpaceHeld] = useState(false);
  const [pendingBbox, setPendingBbox] = useState<[number, number, number, number] | null>(null);
  const [popupPos, setPopupPos] = useState<{ x: number; y: number } | null>(null);

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;
    const resize = () => setSize({ width: Math.max(320, node.clientWidth), height: Math.max(320, node.clientHeight) });
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  function zoomToFit() {
    if (!annotation) return;
    const nextScale = Math.min(size.width / annotation.width, size.height / annotation.height) * 0.95;
    const safeScale = Number.isFinite(nextScale) && nextScale > 0 ? nextScale : 1;
    setTransform({
      scale: safeScale,
      x: (size.width - annotation.width * safeScale) / 2,
      y: (size.height - annotation.height * safeScale) / 2
    });
  }

  useEffect(() => {
    zoomToFit();
    setDrag(null);
    setAxisDraft([]);
  }, [image, annotation?.image_id, annotation?.width, annotation?.height, size.width, size.height]);

  const annotationRef = useRef(annotation);
  annotationRef.current = annotation;
  const transformRef = useRef(transform);
  transformRef.current = transform;
  const modeChangeRef = useRef(onModeChange);
  modeChangeRef.current = onModeChange;
  const selectionChangeRef = useRef(onSelectionChange);
  selectionChangeRef.current = onSelectionChange;

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!annotationRef.current) return;
      if (event.key === " " && !event.repeat) {
        event.preventDefault();
        setSpaceHeld(true);
      }
      if (event.key.toLowerCase() === "c") modeChangeRef.current("bbox");
      if (event.key.toLowerCase() === "e") modeChangeRef.current("axis");
      if (event.key.toLowerCase() === "m") modeChangeRef.current("mask");
      if (event.key.toLowerCase() === "q") modeChangeRef.current("select");
      if (event.key === "Escape") {
        setDrag(null);
        setAxisDraft([]);
        modeChangeRef.current("select");
        selectionChangeRef.current({ objectId: null, handle: null });
      }
      if ((event.ctrlKey || event.metaKey) && (event.key === "+" || event.key === "=")) {
        event.preventDefault();
        zoomBy(1.25);
      }
      if ((event.ctrlKey || event.metaKey) && event.key === "-") {
        event.preventDefault();
        zoomBy(0.8);
      }
      if ((event.ctrlKey || event.metaKey) && event.key === "0") {
        event.preventDefault();
        zoomToFit();
      }
    };
    const onKeyUp = (event: KeyboardEvent) => {
      if (event.key === " ") setSpaceHeld(false);
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, []);

  function stagePointer(): { screen: { x: number; y: number }; image: Point } | null {
    const pointer = stageRef.current?.getPointerPosition();
    if (!pointer) return null;
    return {
      screen: pointer,
      image: [(pointer.x - transform.x) / transform.scale, (pointer.y - transform.y) / transform.scale]
    };
  }

  function zoomBy(factor: number, anchor?: { x: number; y: number }) {
    const oldScale = transform.scale;
    const nextScale = Math.max(0.05, Math.min(20, oldScale * factor));
    const screen = anchor || { x: size.width / 2, y: size.height / 2 };
    const imagePoint = [(screen.x - transform.x) / oldScale, (screen.y - transform.y) / oldScale];
    setTransform({
      scale: nextScale,
      x: screen.x - imagePoint[0] * nextScale,
      y: screen.y - imagePoint[1] * nextScale
    });
  }

  function selectedObject() {
    return annotation?.objects.find((obj) => obj.instance_id === selection.objectId) || null;
  }

  function onMouseDown(event: Konva.KonvaEventObject<MouseEvent>) {
    if (!annotation) return;
    const pointer = stagePointer();
    if (!pointer) return;

    if (mode === "pan" || spaceHeld || event.evt.button === 1) {
      setDrag({ kind: "pan", start: pointer.screen, original: transform });
      return;
    }

    if (!imageBounds(annotation, pointer.image)) return;

    if (!editable) {
      const hit = hitTest(annotation, pointer.image, 12 / transform.scale);
      onSelectionChange(hit);
      return;
    }

    if (mode === "bbox") {
      const imagePoint = clampPoint(pointer.image, annotation);
      setDrag({ kind: "bbox", start: imagePoint, current: imagePoint });
      return;
    }

    if (mode === "axis") {
      let target = selectedObject();
      if (!target) target = findObjectAt(annotation, pointer.image);
      if (!target) {
        onNoObjectForAxis();
        return;
      }
      onSelectionChange({ objectId: target.instance_id, handle: null });
      const imagePoint = clampPoint(pointer.image, annotation);
      const next = [...axisDraft, imagePoint];
      if (next.length === 2) {
        // Complete axis: set main_axis_points
        onAction({ type: "updateObjectMainAxis", instanceId: target.instance_id, mainAxisPoints: next });
        setAxisDraft([]);
        onModeChange("select");
      } else {
        setAxisDraft(next);
      }
      return;
    }

    const hit = hitTest(annotation, pointer.image, 12 / transform.scale);
    onSelectionChange(hit);
    if (hit.objectId && hit.handle && editable) {
      setDrag({ kind: "item", start: pointer.image, selection: hit });
    }
  }

  function onMouseMove() {
    if (!annotation || !drag) return;
    const pointer = stagePointer();
    if (!pointer) return;

    if (drag.kind === "pan") {
      setTransform({
        ...transform,
        x: drag.original.x + (pointer.screen.x - drag.start.x),
        y: drag.original.y + (pointer.screen.y - drag.start.y)
      });
      return;
    }

    if (drag.kind === "bbox") {
      setDrag({ ...drag, current: clampPoint(pointer.image, annotation) });
      return;
    }

    const obj = annotation.objects.find((item) => item.instance_id === drag.selection.objectId);
    if (!obj) return;
    const imagePoint = clampPoint(pointer.image, annotation);
    const dx = imagePoint[0] - drag.start[0];
    const dy = imagePoint[1] - drag.start[1];

    if (drag.selection.handle === "body") {
      onAction({ type: "moveObject", instanceId: obj.instance_id, dx, dy });
      setDrag({ ...drag, start: imagePoint });
    } else if (drag.selection.handle === "axis0" || drag.selection.handle === "axis1") {
      // Dragging axis endpoint — update main_axis_points
      const axisIdx = drag.selection.handle === "axis0" ? 0 : 1;
      if (obj.main_axis_points && obj.main_axis_points.length === 2) {
        const newAxis: Point[] = [...obj.main_axis_points.map((p: Point) => [p[0], p[1]] as Point)];
        newAxis[axisIdx] = imagePoint;
        onAction({ type: "updateObjectMainAxis", instanceId: obj.instance_id, mainAxisPoints: newAxis });
      }
    } else if (drag.selection.handle && ["nw", "ne", "sw", "se"].includes(drag.selection.handle)) {
      onAction({ type: "updateObjectBbox", instanceId: obj.instance_id, bbox: bboxFromHandle(obj, drag.selection.handle, imagePoint) });
    }
  }

  function onMouseUp() {
    if (!annotation || !drag) return;
    if (drag.kind === "bbox") {
      const bbox = normalizeBbox(drag.start, drag.current);
      if (bbox[2] - bbox[0] >= 10 && bbox[3] - bbox[1] >= 10) {
        const pointer = stagePointer();
        if (pointer) {
          setPendingBbox(bbox);
          setPopupPos(pointer.screen);
        }
      }
    }
    setDrag(null);
  }

  function handleClassPick(cls: ClassInfo) {
    if (!pendingBbox) return;
    onAction({ type: "addObject", classInfo: cls, bbox: pendingBbox });
    const nextId = annotation ? Math.max(0, ...annotation.objects.map((obj) => obj.instance_id)) + 1 : 1;
    onSelectionChange({ objectId: nextId, handle: null });
    setPendingBbox(null);
    setPopupPos(null);
  }

  function handleClassCancel() {
    if (!pendingBbox) return;
    onAction(defaultClassAction(pendingBbox));
    const nextId = annotation ? Math.max(0, ...annotation.objects.map((obj) => obj.instance_id)) + 1 : 1;
    onSelectionChange({ objectId: nextId, handle: null });
    setPendingBbox(null);
    setPopupPos(null);
  }

  function onWheel(event: Konva.KonvaEventObject<WheelEvent>) {
    event.evt.preventDefault();
    const pointer = stageRef.current?.getPointerPosition();
    zoomBy(event.evt.deltaY > 0 ? 0.9 : 1.1, pointer || undefined);
  }

  function renderObject(obj: ObjectAnnotation) {
    const selected = selection.objectId === obj.instance_id && !selection.handle?.startsWith("axis");
    const [x1, y1, x2, y2] = obj.bbox_xyxy;
    const handles: [CanvasHandle, Point][] = [
      ["nw", [x1, y1]],
      ["ne", [x2, y1]],
      ["sw", [x1, y2]],
      ["se", [x2, y2]]
    ];
    return (
      <Group key={`obj-${obj.instance_id}`} listening={false}>
        <Rect
          x={x1}
          y={y1}
          width={x2 - x1}
          height={y2 - y1}
          stroke={selected ? "#f97316" : "#22c55e"}
          strokeWidth={(selected ? 3 : 2) / transform.scale}
          fill="rgba(34,197,94,0.08)"
        />
        <Text
          x={x1 + 4}
          y={Math.max(0, y1 - 18 / transform.scale)}
          text={`[${obj.instance_id}] ${obj.class_name || `class_${obj.class_id}`}`}
          fontSize={13 / transform.scale}
          fill="#182230"
        />
        {selected &&
          editable &&
          handles.map(([handle, point]) => (
            <Circle
              key={handle}
              x={point[0]}
              y={point[1]}
              radius={5 / transform.scale}
              fill="#f97316"
              stroke="#fff"
              strokeWidth={1 / transform.scale}
            />
          ))}
      </Group>
    );
  }

  function renderAxis(obj: ObjectAnnotation) {
    if (!obj.main_axis_points || obj.main_axis_points.length < 2) return null;
    const axisSelected = selection.objectId === obj.instance_id &&
      (selection.handle === "axis0" || selection.handle === "axis1");
    const [p0, p1] = obj.main_axis_points;
    const color = axisSelected ? "#f97316" : "#8b5cf6";
    return (
      <Group key={`axis-${obj.instance_id}`} listening={false}>
        {/* Main axis line */}
        <Line
          points={[p0[0], p0[1], p1[0], p1[1]]}
          stroke={color}
          strokeWidth={3 / transform.scale}
          lineCap="round"
        />
        {/* Arrowhead at p1 */}
        <Line
          points={[
            p1[0], p1[1],
            p1[0] - 6 / transform.scale, p1[1] - 6 / transform.scale,
            p1[0] + 6 / transform.scale, p1[1] - 6 / transform.scale
          ]}
          closed
          fill={color}
          stroke={color}
          strokeWidth={1 / transform.scale}
        />
        {/* Axis endpoint handles when selected */}
        {editable && (
          <>
            <Circle
              x={p0[0]} y={p0[1]}
              radius={5 / transform.scale}
              fill={selection.handle === "axis0" ? "#f97316" : "#8b5cf6"}
              stroke="#fff"
              strokeWidth={1 / transform.scale}
            />
            <Circle
              x={p1[0]} y={p1[1]}
              radius={5 / transform.scale}
              fill={selection.handle === "axis1" ? "#f97316" : "#8b5cf6"}
              stroke="#fff"
              strokeWidth={1 / transform.scale}
            />
          </>
        )}
      </Group>
    );
  }

  function renderMaskCandidate(candidate: MaskCandidate | null) {
    if (!candidate) return null;
    const contour = candidate.smooth_contour_px || [];
    const selected = selection.objectId === candidate.instance_id;
    return (
      <Group key={`mask-${candidate.instance_id}`} listening={false}>
        {maskPreview && (
          <KonvaImage
            image={maskPreview}
            x={0}
            y={0}
            width={annotation?.width || candidate.mask_size[0]}
            height={annotation?.height || candidate.mask_size[1]}
            opacity={candidate.stale ? 0.28 : 0.86}
            listening={false}
          />
        )}
        {contour.length > 2 && (
          <Line
            points={contour.flat()}
            closed
            stroke={candidate.stale ? "#dc2626" : selected ? "#0f766e" : "#2563eb"}
            strokeWidth={(selected ? 3 : 2) / transform.scale}
            lineJoin="round"
            listening={false}
          />
        )}
        {candidate.anchor_px && (
          <Group listening={false}>
            <Circle
              x={candidate.anchor_px[0]}
              y={candidate.anchor_px[1]}
              radius={5 / transform.scale}
              fill={candidate.stale ? "#dc2626" : "#0f766e"}
              stroke="#fff"
              strokeWidth={1.5 / transform.scale}
            />
            <Line
              points={[
                candidate.anchor_px[0] - 10 / transform.scale,
                candidate.anchor_px[1],
                candidate.anchor_px[0] + 10 / transform.scale,
                candidate.anchor_px[1],
                candidate.anchor_px[0],
                candidate.anchor_px[1] - 10 / transform.scale,
                candidate.anchor_px[0],
                candidate.anchor_px[1] + 10 / transform.scale
              ]}
              stroke={candidate.stale ? "#dc2626" : "#0f766e"}
              strokeWidth={1.5 / transform.scale}
            />
          </Group>
        )}
      </Group>
    );
  }

  const draftBbox = drag?.kind === "bbox" ? normalizeBbox(drag.start, drag.current) : null;
  const cursor = mode === "pan" || spaceHeld ? "grab" : mode === "bbox" || mode === "axis" ? "crosshair" : "default";
  const selectedObj = selectedObject();

  return (
    <div className="canvas-shell" ref={containerRef} style={{ cursor }}>
      {!annotation && <div className="empty-canvas">Open a dataset and select an image</div>}
      {annotation && (
        <Stage
          ref={stageRef}
          width={size.width}
          height={size.height}
          x={transform.x}
          y={transform.y}
          scaleX={transform.scale}
          scaleY={transform.scale}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onWheel={onWheel}
        >
          <Layer>
            {image && <KonvaImage image={image} x={0} y={0} width={annotation.width} height={annotation.height} listening />}
            {maskOverlayVisible && renderMaskCandidate(maskCandidate)}
            {annotation.objects.map(renderObject)}
            {annotation.objects.map(renderAxis)}
            {draftBbox && (
              <Rect
                x={draftBbox[0]}
                y={draftBbox[1]}
                width={draftBbox[2] - draftBbox[0]}
                height={draftBbox[3] - draftBbox[1]}
                stroke="#3b82f6"
                fill="rgba(59,130,246,0.08)"
                dash={[8 / transform.scale, 4 / transform.scale]}
                strokeWidth={2 / transform.scale}
                listening={false}
              />
            )}
            {axisDraft.length > 0 && (
              <Group listening={false}>
                <Line
                  points={axisDraft.flat()}
                  stroke="#8b5cf6"
                  strokeWidth={3 / transform.scale}
                  dash={[6 / transform.scale, 4 / transform.scale]}
                />
                {axisDraft.map((point, index) => (
                  <Circle
                    key={index}
                    x={point[0]} y={point[1]}
                    radius={5 / transform.scale}
                    fill={index === 0 ? "#a78bfa" : "#8b5cf6"}
                    stroke="#fff"
                    strokeWidth={1 / transform.scale}
                  />
                ))}
              </Group>
            )}
            {mode === "axis" && !selectedObj && editable && (
              <Text
                x={8 / transform.scale}
                y={8 / transform.scale}
                text="Click inside an object first, then draw 2 points for the main axis"
                fontSize={14 / transform.scale}
                fill="#8461c9"
              />
            )}
            {mode === "axis" && axisDraft.length === 1 && selectedObj && editable && (
              <Text
                x={8 / transform.scale}
                y={8 / transform.scale}
                text="Click again to set the main axis end point"
                fontSize={14 / transform.scale}
                fill="#8461c9"
              />
            )}
            {mode === "mask" && (
              <Text
                x={8 / transform.scale}
                y={8 / transform.scale}
                text={maskCandidate ? "Mask review: score with 0-3, G refreshes SAM candidate, O toggles overlay" : "Mask review: select an object, then press G to generate a SAM candidate"}
                fontSize={14 / transform.scale}
                fill="#0f766e"
              />
            )}
          </Layer>
        </Stage>
      )}
      {pendingBbox && popupPos && classes.length > 0 && (
        <ClassPicker
          classes={classes}
          position={popupPos}
          onPick={handleClassPick}
          onCancel={handleClassCancel}
        />
      )}
    </div>
  );
}

export const AnnotationCanvas = memo(AnnotationCanvasInner, (prev, next) => {
  return (
    prev.imageUrl === next.imageUrl &&
    prev.annotation === next.annotation &&
    prev.mode === next.mode &&
    prev.editable === next.editable &&
    prev.selection.objectId === next.selection.objectId &&
    prev.selection.handle === next.selection.handle &&
    prev.classes === next.classes &&
    prev.maskCandidate === next.maskCandidate &&
    prev.maskPreviewUrl === next.maskPreviewUrl &&
    prev.maskOverlayVisible === next.maskOverlayVisible
  );
});

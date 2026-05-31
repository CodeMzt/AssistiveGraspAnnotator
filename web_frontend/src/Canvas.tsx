import { useEffect, useRef, useState } from "react";
import { Circle, Group, Image as KonvaImage, Layer, Line, Rect, Stage, Text } from "react-konva";
import type Konva from "konva";
import type {
  Annotation,
  AnnotationAction,
  CanvasHandle,
  CanvasSelection,
  CanvasTransform,
  GraspAnnotation,
  Mode,
  ObjectAnnotation,
  Point
} from "./types";
import {
  clampPoint,
  centerOf,
  computeP3,
  derivedRotateHandle,
  findObjectAt,
  hitTest,
  normalizeBbox
} from "./geometry";

type Props = {
  imageUrl: string;
  annotation: Annotation | null;
  mode: Mode;
  editable: boolean;
  selection: CanvasSelection;
  onSelectionChange: (selection: CanvasSelection) => void;
  onModeChange: (mode: Mode) => void;
  onAction: (action: AnnotationAction) => void;
  onNoObjectForGrasp: () => void;
  defaultClassAction: (bbox: [number, number, number, number]) => AnnotationAction;
};

type DragState =
  | { kind: "pan"; start: { x: number; y: number }; original: CanvasTransform }
  | { kind: "bbox"; start: Point; current: Point }
  | { kind: "item"; start: Point; selection: CanvasSelection; originalAngle?: number }
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

function selectionIsSame(a: CanvasSelection, b: CanvasSelection) {
  return a.objectId === b.objectId && a.graspId === b.graspId;
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

export function AnnotationCanvas({
  imageUrl,
  annotation,
  mode,
  editable,
  selection,
  onSelectionChange,
  onModeChange,
  onAction,
  onNoObjectForGrasp,
  defaultClassAction
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<Konva.Stage | null>(null);
  const image = useHtmlImage(imageUrl);
  const [size, setSize] = useState({ width: 900, height: 700 });
  const [transform, setTransform] = useState<CanvasTransform>({ scale: 1, x: 0, y: 0 });
  const [drag, setDrag] = useState<DragState>(null);
  const [graspDraft, setGraspDraft] = useState<Point[]>([]);
  const [spaceHeld, setSpaceHeld] = useState(false);

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
    setGraspDraft([]);
  }, [image, annotation?.image_id, annotation?.width, annotation?.height, size.width, size.height]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!annotation) return;
      if (event.key === " " && !event.repeat) {
        event.preventDefault();
        setSpaceHeld(true);
      }
      if (event.key.toLowerCase() === "a") onModeChange("bbox");
      if (event.key.toLowerCase() === "g") onModeChange("grasp");
      if (event.key.toLowerCase() === "v") onModeChange("select");
      if (event.key === "Escape") {
        setDrag(null);
        setGraspDraft([]);
        onModeChange("select");
        onSelectionChange({ objectId: null, graspId: null, handle: null });
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
  }, [annotation, transform, selection]);

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

  function selectedGrasp() {
    const obj = selectedObject();
    return obj?.grasps.find((grasp) => grasp.grasp_id === selection.graspId) || null;
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

    if (mode === "grasp") {
      let target = selectedObject();
      if (!target) target = findObjectAt(annotation, pointer.image);
      if (!target) {
        onNoObjectForGrasp();
        return;
      }
      onSelectionChange({ objectId: target.instance_id, graspId: null, handle: null });
      const imagePoint = clampPoint(pointer.image, annotation);
      const next = [...graspDraft, imagePoint];
      if (next.length === 3) {
        onAction({ type: "addGrasp", instanceId: target.instance_id, points: next });
        const nextId = Math.max(0, ...target.grasps.map((grasp) => grasp.grasp_id)) + 1;
        onSelectionChange({ objectId: target.instance_id, graspId: nextId, handle: null });
        setGraspDraft([]);
      } else {
        setGraspDraft(next);
      }
      return;
    }

    const hit = hitTest(annotation, pointer.image, 12 / transform.scale);
    onSelectionChange(hit);
    if (hit.objectId && hit.handle && editable) {
      const grasp = annotation.objects
        .find((obj) => obj.instance_id === hit.objectId)
        ?.grasps.find((item) => item.grasp_id === hit.graspId);
      const originalAngle = grasp && hit.handle === "rotate" ? Math.atan2(pointer.image[1] - centerOf(grasp.points)[1], pointer.image[0] - centerOf(grasp.points)[0]) : undefined;
      setDrag({ kind: "item", start: pointer.image, selection: hit, originalAngle });
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

    if (!drag.selection.graspId) {
      if (drag.selection.handle === "body") {
        onAction({ type: "moveObject", instanceId: obj.instance_id, dx, dy });
        setDrag({ ...drag, start: imagePoint });
      } else if (drag.selection.handle) {
        onAction({ type: "updateObjectBbox", instanceId: obj.instance_id, bbox: bboxFromHandle(obj, drag.selection.handle, imagePoint) });
      }
      return;
    }

    const grasp = obj.grasps.find((item) => item.grasp_id === drag.selection.graspId);
    if (!grasp) return;
    if (drag.selection.handle === "body") {
      onAction({ type: "moveGrasp", instanceId: obj.instance_id, graspId: grasp.grasp_id, dx, dy });
      setDrag({ ...drag, start: imagePoint });
    } else if (drag.selection.handle === "rotate") {
      const center = centerOf(grasp.points);
      const angle = Math.atan2(imagePoint[1] - center[1], imagePoint[0] - center[0]) - (drag.originalAngle ?? 0);
      onAction({ type: "rotateGrasp", instanceId: obj.instance_id, graspId: grasp.grasp_id, angle });
      setDrag({ ...drag, originalAngle: Math.atan2(imagePoint[1] - center[1], imagePoint[0] - center[0]) });
    } else if (drag.selection.handle?.startsWith("p")) {
      const pointIndex = Number(drag.selection.handle.slice(1));
      if (pointIndex < 3) {
        onAction({ type: "updateGraspPoint", instanceId: obj.instance_id, graspId: grasp.grasp_id, pointIndex, point: imagePoint });
      }
    }
  }

  function onMouseUp() {
    if (!annotation || !drag) return;
    if (drag.kind === "bbox") {
      const bbox = normalizeBbox(drag.start, drag.current);
      if (bbox[2] - bbox[0] >= 10 && bbox[3] - bbox[1] >= 10) {
        onAction(defaultClassAction(bbox));
        const nextId = Math.max(0, ...annotation.objects.map((obj) => obj.instance_id)) + 1;
        onSelectionChange({ objectId: nextId, graspId: null, handle: null });
      }
    }
    setDrag(null);
  }

  function onWheel(event: Konva.KonvaEventObject<WheelEvent>) {
    event.evt.preventDefault();
    const pointer = stageRef.current?.getPointerPosition();
    zoomBy(event.evt.deltaY > 0 ? 0.9 : 1.1, pointer || undefined);
  }

  function renderObject(obj: ObjectAnnotation) {
    const selected = selection.objectId === obj.instance_id && selection.graspId == null;
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

  function renderGrasp(obj: ObjectAnnotation, grasp: GraspAnnotation) {
    const selected = selection.objectId === obj.instance_id && selection.graspId === grasp.grasp_id;
    const rotate = derivedRotateHandle(grasp);
    return (
      <Group key={`grasp-${obj.instance_id}-${grasp.grasp_id}`} listening={false}>
        <Line
          points={grasp.points.flat()}
          closed
          stroke={selected ? "#38bdf8" : "#a78bfa"}
          strokeWidth={(selected ? 3 : 2) / transform.scale}
          fill="rgba(167,139,250,0.08)"
        />
        <Line points={[...grasp.points[0], ...grasp.points[1]]} stroke="#22d3ee" strokeWidth={2 / transform.scale} />
        <Line points={[...grasp.points[1], ...grasp.points[2]]} stroke="#f472b6" strokeWidth={2 / transform.scale} />
        {selected &&
          editable &&
          grasp.points.map((point, index) => (
            <Circle
              key={index}
              x={point[0]}
              y={point[1]}
              radius={index === 3 ? 3 / transform.scale : 5 / transform.scale}
              fill={index < 2 ? "#22d3ee" : index === 2 ? "#f472b6" : "#94a3b8"}
              stroke="#fff"
              strokeWidth={1 / transform.scale}
            />
          ))}
        {selected && editable && (
          <>
            <Line points={[...centerOf(grasp.points), ...rotate]} stroke="#fbbf24" strokeWidth={1 / transform.scale} dash={[4 / transform.scale, 4 / transform.scale]} />
            <Circle x={rotate[0]} y={rotate[1]} radius={5 / transform.scale} fill="#fbbf24" stroke="#fff" strokeWidth={1 / transform.scale} />
          </>
        )}
      </Group>
    );
  }

  const draftBbox = drag?.kind === "bbox" ? normalizeBbox(drag.start, drag.current) : null;
  const previewP3 = graspDraft.length === 3 ? computeP3(graspDraft[0], graspDraft[1], graspDraft[2]) : null;
  const cursor = mode === "pan" || spaceHeld ? "grab" : mode === "bbox" || mode === "grasp" ? "crosshair" : "default";
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
            {annotation.objects.map(renderObject)}
            {annotation.objects.flatMap((obj) => obj.grasps.map((grasp) => renderGrasp(obj, grasp)))}
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
            {graspDraft.length > 0 && (
              <Group listening={false}>
                <Line points={graspDraft.flat()} stroke="#22d3ee" strokeWidth={2 / transform.scale} dash={[6 / transform.scale, 4 / transform.scale]} />
                {previewP3 && (
                  <Line
                    points={[...graspDraft[0], ...graspDraft[1], ...graspDraft[2], ...previewP3]}
                    closed
                    stroke="#f472b6"
                    strokeWidth={2 / transform.scale}
                    dash={[6 / transform.scale, 4 / transform.scale]}
                  />
                )}
                {graspDraft.map((point, index) => (
                  <Circle key={index} x={point[0]} y={point[1]} radius={5 / transform.scale} fill={index < 2 ? "#22d3ee" : "#f472b6"} />
                ))}
              </Group>
            )}
            {mode === "grasp" && !selectedObj && editable && (
              <Text x={8 / transform.scale} y={8 / transform.scale} text="Select or click inside an object before drawing a grasp" fontSize={14 / transform.scale} fill="#a15c07" />
            )}
          </Layer>
        </Stage>
      )}
    </div>
  );
}

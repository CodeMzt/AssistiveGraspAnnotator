"""Image canvas — QGraphicsView subclass for annotation display and interaction."""

from __future__ import annotations

from enum import Enum, auto
from typing import Optional

from PySide6.QtCore import (
    QPointF,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTransform,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QGraphicsEllipseItem,
)

from assistive_grasp_annotator.models.annotation import (
    AnnotationModel,
    GraspAnnotation,
    ObjectAnnotation,
    DIFFICULTY_MAP,
)
from assistive_grasp_annotator.models.classes import ClassRegistry
from assistive_grasp_annotator.tools.geometry import (
    compute_p3,
    grasp_center,
    rotate_grasp,
    move_grasp,
    point_point_distance,
)


# ---------------------------------------------------------------------------
# Color palette for object classes (10 distinct colors + cycling)
# ---------------------------------------------------------------------------

CLASS_COLORS = [
    QColor(63, 140, 255),   # blue
    QColor(255, 159, 64),    # orange
    QColor(76, 209, 55),     # green
    QColor(255, 71, 87),     # red
    QColor(165, 94, 234),    # purple
    QColor(255, 200, 0),     # yellow
    QColor(0, 210, 210),     # cyan
    QColor(255, 105, 180),   # hot pink
    QColor(128, 255, 128),   # light green
    QColor(180, 180, 255),   # lavender
]


def class_color(class_id: int) -> QColor:
    return CLASS_COLORS[class_id % len(CLASS_COLORS)]


DIFFICULTY_COLORS = {
    "easy": QColor(76, 209, 55, 180),
    "medium": QColor(255, 200, 0, 180),
    "hard": QColor(255, 159, 64, 180),
    "invalid": QColor(255, 71, 87, 180),
}

DIFFICULTY_LINE_COLORS = {
    "easy": QColor(76, 209, 55),
    "medium": QColor(255, 200, 0),
    "hard": QColor(255, 159, 64),
    "invalid": QColor(255, 71, 87),
}


# ---------------------------------------------------------------------------
# CanvasMode
# ---------------------------------------------------------------------------

class CanvasMode(Enum):
    SELECT = auto()
    BBOX = auto()
    GRASP = auto()
    PAN = auto()


# ---------------------------------------------------------------------------
# Custom Graphics Items
# ---------------------------------------------------------------------------

HANDLE_SIZE = 8.0
HANDLE_HIT_MARGIN = 6.0


class BboxGraphicsItem(QGraphicsRectItem):
    """Visual representation of an object bounding box with resize handles."""

    def __init__(self, obj: ObjectAnnotation, index: int, parent=None):
        super().__init__(parent)
        self._obj = obj
        self._index = index
        self._color = class_color(obj.class_id)
        self._selected = False
        self._hovered_handle: Optional[str] = None

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self._rebuild()

    @property
    def obj_instance_id(self) -> int:
        return self._obj.instance_id

    def _rebuild(self):
        x1, y1, x2, y2 = self._obj.bbox_xyxy
        self.setRect(QRectF(x1, y1, x2 - x1, y2 - y1))

        pen = QPen(self._color, 2.5)
        pen.setCosmetic(True)
        self.setPen(pen)

        if self._selected:
            fill = QColor(self._color.red(), self._color.green(), self._color.blue(), 40)
        else:
            fill = QColor(self._color.red(), self._color.green(), self._color.blue(), 15)
        self.setBrush(QBrush(fill))

    def set_selected(self, sel: bool):
        self._selected = sel
        self._rebuild()

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)

        if not self._selected:
            return

        # Draw label
        rect = self.rect()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        label = f"{self._obj.class_name or f'class_{self._obj.class_id}'} #{self._obj.instance_id}"
        font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        painter.setFont(font)
        fm = painter.fontMetrics()
        txt_w = fm.horizontalAdvance(label) + 8
        txt_h = fm.height() + 4
        txt_y = rect.top() - txt_h - 2
        if txt_y < 0:
            txt_y = rect.top()
        txt_rect = QRectF(rect.left(), txt_y, txt_w, txt_h)
        painter.drawRect(txt_rect)
        painter.setPen(QPen(Qt.GlobalColor.white))
        painter.drawText(txt_rect, Qt.AlignmentFlag.AlignCenter, label)

        # Draw resize handles
        painter.setPen(QPen(self._color, 1.5))
        painter.setBrush(QBrush(Qt.GlobalColor.white))
        for hx, hy, _ in self._handle_positions():
            painter.drawRect(QRectF(hx - HANDLE_SIZE / 2, hy - HANDLE_SIZE / 2,
                                    HANDLE_SIZE, HANDLE_SIZE))

    def _handle_positions(self) -> list[tuple[float, float, str]]:
        r = self.rect()
        return [
            (r.left(), r.top(), "tl"),
            (r.center().x(), r.top(), "t"),
            (r.right(), r.top(), "tr"),
            (r.right(), r.center().y(), "r"),
            (r.right(), r.bottom(), "br"),
            (r.center().x(), r.bottom(), "b"),
            (r.left(), r.bottom(), "bl"),
            (r.left(), r.center().y(), "l"),
        ]

    def handle_at(self, scene_pos: QPointF) -> Optional[str]:
        for hx, hy, name in self._handle_positions():
            if abs(scene_pos.x() - hx) <= HANDLE_SIZE / 2 + HANDLE_HIT_MARGIN and \
               abs(scene_pos.y() - hy) <= HANDLE_SIZE / 2 + HANDLE_HIT_MARGIN:
                return name
        if self.rect().contains(scene_pos):
            return "body"
        return None

    def resize_from_handle(self, handle: str, delta: QPointF):
        x1, y1, x2, y2 = self._obj.bbox_xyxy
        dx, dy = delta.x(), delta.y()
        if "l" in handle:
            x1 += dx
        if "r" in handle:
            x2 += dx
        if "t" in handle:
            y1 += dy
        if "b" in handle:
            y2 += dy
        if x1 >= x2:
            x1 = x2 - 1
        if y1 >= y2:
            y1 = y2 - 1
        self._obj.bbox_xyxy = [x1, y1, x2, y2]
        self._rebuild()

    def move_by(self, delta: QPointF):
        x1, y1, x2, y2 = self._obj.bbox_xyxy
        self._obj.bbox_xyxy = [x1 + delta.x(), y1 + delta.y(), x2 + delta.x(), y2 + delta.y()]
        self._rebuild()

    def update_geometry(self):
        self._rebuild()


class GraspGraphicsItem(QGraphicsPolygonItem):
    """Visual representation of a grasp rectangle with axis indicators."""

    def __init__(self, grasp: GraspAnnotation, color: QColor, parent=None):
        super().__init__(parent)
        self._grasp = grasp
        self._color = color
        self._selected = False
        self._hovered_handle: Optional[str] = None

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self._rebuild()

    @property
    def grasp_id(self) -> int:
        return self._grasp.grasp_id

    def _rebuild(self):
        pts = self._grasp.points
        poly = QPolygonF()
        for p in pts:
            poly.append(QPointF(p[0], p[1]))
        self.setPolygon(poly)

        diff_color = DIFFICULTY_LINE_COLORS.get(self._grasp.difficulty, self._color)
        pen = QPen(diff_color, 2.0)
        pen.setCosmetic(True)
        self.setPen(pen)

        fill = DIFFICULTY_COLORS.get(self._grasp.difficulty,
                                     QColor(self._color.red(), self._color.green(),
                                            self._color.blue(), 100))
        self.setBrush(QBrush(fill))

    def set_selected(self, sel: bool):
        self._selected = sel
        self._rebuild()

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)

        if not self._selected:
            return

        pts = self._grasp.points
        if len(pts) < 4:
            return
        p0 = QPointF(pts[0][0], pts[0][1])
        p1 = QPointF(pts[1][0], pts[1][1])
        p2 = QPointF(pts[2][0], pts[2][1])
        p3 = QPointF(pts[3][0], pts[3][1])

        # Width axis arrow (p0 → p1)
        width_pen = QPen(QColor(0, 255, 255), 2.5)
        width_pen.setCosmetic(True)
        painter.setPen(width_pen)
        painter.drawLine(p0, p1)

        # Arrow head at p1
        self._draw_arrow_head(painter, p0, p1, QColor(0, 255, 255))

        # Depth axis arrow (p1 → p2)
        depth_pen = QPen(QColor(255, 0, 255), 2.5)
        depth_pen.setCosmetic(True)
        painter.setPen(depth_pen)
        painter.drawLine(p1, p2)
        self._draw_arrow_head(painter, p1, p2, QColor(255, 0, 255))

        # Corner handles
        painter.setPen(QPen(Qt.GlobalColor.white, 1.5))
        for p in [p0, p1, p2, p3]:
            painter.setBrush(QBrush(Qt.GlobalColor.white))
            painter.drawRect(QRectF(p.x() - HANDLE_SIZE / 2, p.y() - HANDLE_SIZE / 2,
                                    HANDLE_SIZE, HANDLE_SIZE))

        # Rotation handle (midpoint of width axis)
        mid_w = (p0 + p1) / 2.0
        painter.setBrush(QBrush(QColor(255, 255, 0)))
        painter.setPen(QPen(QColor(255, 255, 0), 2))
        painter.drawEllipse(mid_w, HANDLE_SIZE / 2, HANDLE_SIZE / 2)

        # Label
        center = (p0 + p1 + p2 + p3) / 4.0
        painter.setPen(QPen(Qt.GlobalColor.black, 1))
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        label = f"G{self._grasp.grasp_id} ({self._grasp.difficulty})"
        painter.drawText(center + QPointF(10, 10), label)

    def _draw_arrow_head(self, painter, fr: QPointF, to: QPointF, color: QColor):
        dx = to.x() - fr.x()
        dy = to.y() - fr.y()
        length = (dx * dx + dy * dy) ** 0.5
        if length < 1e-6:
            return
        ux, uy = dx / length, dy / length
        px, py = -uy, ux  # perpendicular
        arrow_len = min(12.0, length * 0.3)

        tip = to
        base_left = to - QPointF(ux * arrow_len, uy * arrow_len) + QPointF(px * arrow_len * 0.4, py * arrow_len * 0.4)
        base_right = to - QPointF(ux * arrow_len, uy * arrow_len) - QPointF(px * arrow_len * 0.4, py * arrow_len * 0.4)

        path = QPainterPath()
        path.moveTo(tip)
        path.lineTo(base_left)
        path.lineTo(base_right)
        path.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawPath(path)

    def handle_at(self, scene_pos: QPointF) -> Optional[str]:
        pts = self._grasp.points
        if len(pts) < 4:
            return None
        # Check corner handles
        labels = ["p0", "p1", "p2", "p3"]
        for i, p in enumerate(pts):
            if abs(scene_pos.x() - p[0]) <= HANDLE_SIZE / 2 + HANDLE_HIT_MARGIN and \
               abs(scene_pos.y() - p[1]) <= HANDLE_SIZE / 2 + HANDLE_HIT_MARGIN:
                return labels[i]
        # Check rotation handle
        mid_x = (pts[0][0] + pts[1][0]) / 2
        mid_y = (pts[0][1] + pts[1][1]) / 2
        d = point_point_distance(scene_pos.x(), scene_pos.y(), mid_x, mid_y)
        if d <= HANDLE_SIZE + HANDLE_HIT_MARGIN:
            return "rotate"
        # Check body
        from assistive_grasp_annotator.tools.geometry import point_in_polygon
        flat = [(p[0], p[1]) for p in pts]
        if point_in_polygon(scene_pos.x(), scene_pos.y(), flat):
            return "body"
        return None

    def update_geometry(self):
        self._rebuild()


# ---------------------------------------------------------------------------
# Drawing preview items
# ---------------------------------------------------------------------------

class DrawingPreview:
    """Temporary items shown during bbox/grasp drawing."""

    def __init__(self, scene: QGraphicsScene):
        self._scene = scene
        self._items: list[QGraphicsItem] = []

    def clear(self):
        for item in self._items:
            self._scene.removeItem(item)
        self._items.clear()

    def add_rect(self, rect: QRectF, pen_color: QColor, fill_color: QColor) -> QGraphicsRectItem:
        item = QGraphicsRectItem(rect)
        item.setPen(QPen(pen_color, 2))
        item.setBrush(QBrush(fill_color))
        self._scene.addItem(item)
        self._items.append(item)
        return item

    def add_line(self, p1: QPointF, p2: QPointF, color: QColor, width: float = 2) -> QGraphicsLineItem:
        item = QGraphicsLineItem(p1.x(), p1.y(), p2.x(), p2.y())
        pen = QPen(color, width)
        pen.setCosmetic(True)
        item.setPen(pen)
        self._scene.addItem(item)
        self._items.append(item)
        return item

    def add_dot(self, pos: QPointF, color: QColor, radius: float = 5) -> QGraphicsEllipseItem:
        item = QGraphicsEllipseItem(pos.x() - radius, pos.y() - radius, radius * 2, radius * 2)
        item.setPen(Qt.PenStyle.NoPen)
        item.setBrush(QBrush(color))
        self._scene.addItem(item)
        self._items.append(item)
        return item

    def add_poly(self, points: list[QPointF], pen_color: QColor, fill_color: QColor) -> QGraphicsPolygonItem:
        item = QGraphicsPolygonItem()
        item.setPolygon(QPolygonF(points))
        item.setPen(QPen(pen_color, 2))
        item.setBrush(QBrush(fill_color))
        self._scene.addItem(item)
        self._items.append(item)
        return item


# ---------------------------------------------------------------------------
# ImageCanvas
# ---------------------------------------------------------------------------

class ImageCanvas(QGraphicsView):
    """Main annotation canvas with zoom, pan, bbox and grasp drawing."""

    mode_changed = Signal(CanvasMode)
    selection_changed = Signal(object, object)  # obj or None, grasp or None
    bbox_added = Signal(ObjectAnnotation)
    grasp_added = Signal(int, GraspAnnotation)  # instance_id, grasp
    annotation_modified = Signal()
    mouse_position_changed = Signal(float, float)
    drawing_cancelled = Signal()
    no_object_for_grasp = Signal()

    MIN_ZOOM = 0.05
    MAX_ZOOM = 20.0

    def __init__(self, parent=None):
        super().__init__(parent)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._annotation: Optional[AnnotationModel] = None
        self._image_item: Optional[QGraphicsPixmapItem] = None
        self._class_registry: Optional[ClassRegistry] = None

        # Graphics item containers
        self._bbox_items: dict[int, BboxGraphicsItem] = {}
        self._grasp_items: dict[tuple[int, int], GraspGraphicsItem] = {}  # (inst_id, grasp_id)

        # Mode
        self._mode: CanvasMode = CanvasMode.SELECT
        self._space_held: bool = False

        # Bbox drawing state
        self._drawing_bbox: bool = False
        self._bbox_start: Optional[QPointF] = None
        self._bbox_preview: Optional[DrawingPreview] = None

        # Grasp drawing state
        self._drawing_grasp: bool = False
        self._grasp_points: list[QPointF] = []
        self._grasp_preview: Optional[DrawingPreview] = None
        self._grasp_target_instance: Optional[int] = None

        # Select/move state
        self._dragging: bool = False
        self._drag_start: Optional[QPointF] = None
        self._drag_item: Optional[QGraphicsItem] = None
        self._drag_handle: Optional[str] = None
        self._drag_original_bbox: Optional[list[float]] = None
        self._drag_original_grasp_pts: Optional[list[list[float]]] = None

        self._selected_obj: Optional[ObjectAnnotation] = None
        self._selected_grasp: Optional[GraspAnnotation] = None

        # Pan state
        self._panning: bool = False
        self._pan_start: Optional[QPointF] = None

        # Setup
        self.setRenderHints(
            self.renderHints()
            | QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_image_and_annotation(
        self, image_path, annotation: AnnotationModel,
        class_registry: Optional[ClassRegistry] = None,
    ):
        self._annotation = annotation
        self._class_registry = class_registry
        self._selected_obj = None
        self._selected_grasp = None

        # Clear previous
        self._clear_all_items()
        self._scene.clear()

        # Load image
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            self._image_item = None
            return

        annotation.image_size = (pixmap.width(), pixmap.height())
        annotation.image_path = image_path

        self._image_item = QGraphicsPixmapItem(pixmap)
        self._scene.addItem(self._image_item)
        self._scene.setSceneRect(self._image_item.boundingRect())

        self._redraw_all_items()
        self.zoom_to_fit()

    def set_mode(self, mode: CanvasMode):
        prev = self._mode
        self._mode = mode
        if prev == mode:
            return
        self._cancel_drawing()
        if mode == CanvasMode.BBOX:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif mode == CanvasMode.GRASP:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif mode == CanvasMode.PAN:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.mode_changed.emit(mode)

    def cycle_mode(self):
        modes = [CanvasMode.SELECT, CanvasMode.BBOX, CanvasMode.GRASP]
        try:
            idx = modes.index(self._mode)
            self.set_mode(modes[(idx + 1) % len(modes)])
        except ValueError:
            self.set_mode(CanvasMode.SELECT)

    def current_mode(self) -> CanvasMode:
        return self._mode

    def _restore_mode_cursor(self):
        if self._mode == CanvasMode.BBOX or self._mode == CanvasMode.GRASP:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self._mode == CanvasMode.PAN:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    # --- Zoom ---

    def zoom_in(self):
        self._zoom_by(1.25)

    def zoom_out(self):
        self._zoom_by(0.8)

    def zoom_to_fit(self):
        if self._image_item is None:
            return
        self.fitInView(self._image_item, Qt.AspectRatioMode.KeepAspectRatio)

    def zoom_original(self):
        self.resetTransform()

    def _zoom_by(self, factor: float):
        t = self.transform()
        sx = t.m11()
        if (sx < self.MIN_ZOOM and factor < 1) or (sx > self.MAX_ZOOM and factor > 1):
            return
        self.scale(factor, factor)

    # --- Selection ---

    def select_object(self, obj: Optional[ObjectAnnotation]):
        self._selected_obj = obj
        self._selected_grasp = None
        self._update_selection_visuals()
        self.selection_changed.emit(obj, None)

    def select_grasp(self, obj: Optional[ObjectAnnotation], grasp: Optional[GraspAnnotation]):
        self._selected_obj = obj
        self._selected_grasp = grasp
        self._update_selection_visuals()
        self.selection_changed.emit(obj, grasp)

    def delete_selected(self):
        if self._annotation is None:
            return
        if self._selected_grasp and self._selected_obj:
            self._annotation.remove_grasp(
                self._selected_obj.instance_id, self._selected_grasp.grasp_id)
            self._selected_grasp = None
            self._redraw_all_items()
            self.annotation_modified.emit()
        elif self._selected_obj:
            inst_id = self._selected_obj.instance_id
            self._annotation.remove_object(inst_id)
            self._selected_obj = None
            self._selected_grasp = None
            self._redraw_all_items()
            self.annotation_modified.emit()

    # ------------------------------------------------------------------
    # Internal — drawing management
    # ------------------------------------------------------------------

    def _clear_all_items(self):
        self._bbox_items.clear()
        self._grasp_items.clear()
        self._cancel_drawing()

    def _redraw_all_items(self):
        self._clear_graphics_items()
        if self._annotation is None:
            return
        for obj in self._annotation.objects:
            self._add_bbox_graphics(obj)
            for grasp in obj.grasps:
                self._add_grasp_graphics(obj, grasp)
        self._update_selection_visuals()

    def _clear_graphics_items(self):
        for item in list(self._bbox_items.values()):
            self._scene.removeItem(item)
        self._bbox_items.clear()
        for item in list(self._grasp_items.values()):
            self._scene.removeItem(item)
        self._grasp_items.clear()

    def _add_bbox_graphics(self, obj: ObjectAnnotation):
        idx = len([i for i in self._bbox_items if self._bbox_items[i]._obj.instance_id <= obj.instance_id])
        item = BboxGraphicsItem(obj, idx)
        self._bbox_items[obj.instance_id] = item
        self._scene.addItem(item)

    def _add_grasp_graphics(self, obj: ObjectAnnotation, grasp: GraspAnnotation):
        color = class_color(obj.class_id)
        item = GraspGraphicsItem(grasp, color)
        self._grasp_items[(obj.instance_id, grasp.grasp_id)] = item
        self._scene.addItem(item)

    def _update_selection_visuals(self):
        for inst_id, item in self._bbox_items.items():
            item.set_selected(self._selected_obj is not None and inst_id == self._selected_obj.instance_id)
        for (inst_id, gid), item in self._grasp_items.items():
            sel = (self._selected_grasp is not None and
                   self._selected_obj is not None and
                   inst_id == self._selected_obj.instance_id and
                   gid == self._selected_grasp.grasp_id)
            item.set_selected(sel)

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def wheelEvent(self, event):
        factor = 1.1 if event.angleDelta().y() > 0 else 0.9
        self._zoom_by(factor)
        event.accept()

    def mousePressEvent(self, event):
        scene_pos = self.mapToScene(event.pos())

        if self._mode == CanvasMode.PAN or (event.button() == Qt.MouseButton.MiddleButton):
            self._start_pan(event, scene_pos)
            return

        if self._space_held and event.button() == Qt.MouseButton.LeftButton:
            self._start_pan(event, scene_pos)
            return

        if self._mode == CanvasMode.BBOX:
            self._start_bbox(event, scene_pos)
        elif self._mode == CanvasMode.GRASP:
            self._start_grasp(event, scene_pos)
        elif self._mode == CanvasMode.SELECT:
            self._start_select(event, scene_pos)

    def mouseMoveEvent(self, event):
        scene_pos = self.mapToScene(event.pos())
        self.mouse_position_changed.emit(scene_pos.x(), scene_pos.y())

        if self._panning:
            self._update_pan(event)
            return

        if self._dragging:
            self._update_drag(scene_pos)
            return

        if self._drawing_bbox:
            self._update_bbox(scene_pos)
            return

        if self._mode == CanvasMode.GRASP:
            self._update_grasp_preview(scene_pos)
            return

        if self._mode == CanvasMode.SELECT:
            self._update_select_hover(scene_pos)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self._panning:
            self._end_pan(event)
            return

        if self._dragging:
            self._end_drag(event)
            return

        if self._drawing_bbox:
            self._end_bbox(event)
            return

    def mouseDoubleClickEvent(self, event):
        pass  # Reserved

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = False
            self._restore_mode_cursor()
            return
        super().keyReleaseEvent(event)

    # ------------------------------------------------------------------
    # Pan
    # ------------------------------------------------------------------

    def _start_pan(self, event, scene_pos):
        self._panning = True
        self._pan_start = event.pos()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def _update_pan(self, event):
        delta = event.pos() - self._pan_start
        self._pan_start = event.pos()
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
        event.accept()

    def _end_pan(self, event):
        self._panning = False
        self._pan_start = None
        if self._space_held:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif self._mode == CanvasMode.PAN:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self._restore_mode_cursor()

    # ------------------------------------------------------------------
    # BBox drawing
    # ------------------------------------------------------------------

    def _start_bbox(self, event, scene_pos):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._drawing_bbox = True
        self._bbox_start = scene_pos
        self._bbox_preview = DrawingPreview(self._scene)
        event.accept()

    def _update_bbox(self, scene_pos):
        if self._bbox_preview is None or self._bbox_start is None:
            return
        self._bbox_preview.clear()
        rect = QRectF(self._bbox_start, scene_pos).normalized()
        self._bbox_preview.add_rect(rect, QColor(63, 140, 255), QColor(63, 140, 255, 30))

    def _end_bbox(self, event):
        if not self._drawing_bbox or self._bbox_preview is None or self._bbox_start is None or self._annotation is None:
            self._cancel_drawing()
            return
        scene_pos = self.mapToScene(event.pos())
        self._bbox_preview.clear()
        self._bbox_preview = None

        rect = QRectF(self._bbox_start, scene_pos).normalized()
        if rect.width() < 10 or rect.height() < 10:
            self._drawing_bbox = False
            self._bbox_start = None
            return

        bbox = [rect.left(), rect.top(), rect.right(), rect.bottom()]

        # Determine class: use class_registry default or first class
        class_id = 0
        class_name = ""
        graspable = True
        policy = "grasp_rect"
        if self._class_registry is not None and self._class_registry.class_count() > 0:
            cls = self._class_registry.all_classes()[0]
            class_id = cls.id
            class_name = cls.name
            graspable = cls.graspable
            policy = cls.policy

        obj = self._annotation.add_object(class_id, bbox, class_name, graspable, policy)
        self._drawing_bbox = False
        self._bbox_start = None

        self._redraw_all_items()
        self.select_object(obj)
        self.bbox_added.emit(obj)

    # ------------------------------------------------------------------
    # Grasp drawing
    # ------------------------------------------------------------------

    def _start_grasp(self, event, scene_pos):
        if event.button() != Qt.MouseButton.LeftButton:
            return

        if not self._drawing_grasp:
            # First click: start new grasp
            if self._annotation is None:
                return
            # Determine target object
            if self._selected_obj is not None:
                self._grasp_target_instance = self._selected_obj.instance_id
            else:
                obj = self._annotation.find_object_at(scene_pos.x(), scene_pos.y())
                if obj is not None:
                    self._grasp_target_instance = obj.instance_id
                else:
                    # No object selected and none under cursor — cannot draw grasp
                    self.no_object_for_grasp.emit()
                    return

            self._drawing_grasp = True
            self._grasp_points = [scene_pos]
            self._grasp_preview = DrawingPreview(self._scene)
            self._grasp_preview.add_dot(scene_pos, QColor(0, 255, 255), 6)
            event.accept()
            return

        # Subsequent clicks
        self._grasp_points.append(scene_pos)

        if len(self._grasp_points) == 2:
            self._grasp_preview.clear()
            self._grasp_preview.add_dot(self._grasp_points[0], QColor(0, 255, 255), 6)
            self._grasp_preview.add_dot(self._grasp_points[1], QColor(0, 255, 255), 6)
            self._grasp_preview.add_line(self._grasp_points[0], self._grasp_points[1],
                                         QColor(0, 255, 255), 2.5)

        elif len(self._grasp_points) == 3:
            # Compute p3 and finish
            p0 = self._grasp_points[0]
            p1 = self._grasp_points[1]
            p2 = self._grasp_points[2]
            p3 = QPointF(p0.x() + p2.x() - p1.x(), p0.y() + p2.y() - p1.y())
            self._grasp_points.append(p3)

            self._finish_grasp()
            event.accept()
            return

        event.accept()

    def _update_grasp_preview(self, scene_pos):
        if not self._drawing_grasp or self._grasp_preview is None:
            return
        if len(self._grasp_points) == 2:
            self._grasp_preview.clear()
            self._grasp_preview.add_dot(self._grasp_points[0], QColor(0, 255, 255), 6)
            self._grasp_preview.add_dot(self._grasp_points[1], QColor(0, 255, 255), 6)
            self._grasp_preview.add_line(self._grasp_points[0], self._grasp_points[1],
                                         QColor(0, 255, 255), 2.5)
            # Preview depth
            p2 = scene_pos
            self._grasp_preview.add_line(self._grasp_points[1], p2, QColor(255, 0, 255, 150), 2)
            self._grasp_preview.add_dot(p2, QColor(255, 0, 255, 200), 5)

    def _finish_grasp(self):
        if self._annotation is None or self._grasp_target_instance is None:
            self._cancel_drawing()
            return

        pts = [[p.x(), p.y()] for p in self._grasp_points]
        grasp = self._annotation.add_grasp(self._grasp_target_instance, pts)
        if grasp is not None:
            self._redraw_all_items()
            obj = self._annotation.get_object_by_instance(self._grasp_target_instance)
            self.select_grasp(obj, grasp)
            self.grasp_added.emit(self._grasp_target_instance, grasp)

        self._cancel_drawing()

    def _cancel_drawing(self):
        if self._bbox_preview:
            self._bbox_preview.clear()
            self._bbox_preview = None
        if self._grasp_preview:
            self._grasp_preview.clear()
            self._grasp_preview = None
        self._drawing_bbox = False
        self._bbox_start = None
        self._drawing_grasp = False
        self._grasp_points = []
        self._grasp_target_instance = None
        self.drawing_cancelled.emit()

    # ------------------------------------------------------------------
    # Select / Move / Resize
    # ------------------------------------------------------------------

    def _start_select(self, event, scene_pos):
        if event.button() != Qt.MouseButton.LeftButton:
            return

        # Check grasp hit first (higher priority)
        if self._annotation is not None:
            obj, grasp = self._annotation.find_grasp_at(scene_pos.x(), scene_pos.y(), threshold=15)
            if grasp is not None and obj is not None:
                key = (obj.instance_id, grasp.grasp_id)
                if key in self._grasp_items:
                    item = self._grasp_items[key]
                    handle = item.handle_at(scene_pos)
                    if handle is not None:
                        self._start_item_drag(item, handle, scene_pos)
                        self.select_grasp(obj, grasp)
                        return

        # Check bbox hit
        for inst_id, item in reversed(list(self._bbox_items.items())):
            handle = item.handle_at(scene_pos)
            if handle is not None:
                obj = self._annotation.get_object_by_instance(inst_id) if self._annotation else None
                self._start_item_drag(item, handle, scene_pos)
                self.select_object(obj)
                return

        # Click on empty space: deselect
        self.select_object(None)

    def _start_item_drag(self, item, handle: str, scene_pos: QPointF):
        self._dragging = True
        self._drag_start = scene_pos
        self._drag_item = item
        self._drag_handle = handle

        if isinstance(item, BboxGraphicsItem):
            self._drag_original_bbox = list(item._obj.bbox_xyxy)
        elif isinstance(item, GraspGraphicsItem):
            self._drag_original_grasp_pts = [[p[0], p[1]] for p in item._grasp.points]

    def _update_drag(self, scene_pos):
        if self._drag_start is None or self._drag_item is None:
            return
        delta = scene_pos - self._drag_start
        self._drag_start = scene_pos

        if isinstance(self._drag_item, BboxGraphicsItem):
            if self._drag_handle == "body":
                self._drag_item.move_by(delta)
            elif self._drag_handle is not None:
                self._drag_item.resize_from_handle(self._drag_handle, delta)

        elif isinstance(self._drag_item, GraspGraphicsItem):
            grasp = self._drag_item._grasp
            if self._drag_handle == "body":
                pts = move_grasp(
                    [(p[0], p[1]) for p in grasp.points],
                    delta.x(), delta.y(),
                )
                grasp.set_points_from_flat(pts)
            elif self._drag_handle == "rotate":
                center = grasp_center([(p[0], p[1]) for p in grasp.points])
                angle = delta.x() * 0.02  # Sensitivity
                pts = rotate_grasp(
                    [(p[0], p[1]) for p in grasp.points],
                    angle, center,
                )
                grasp.set_points_from_flat(pts)
            elif self._drag_handle in ("p0", "p1", "p2", "p3"):
                idx = {"p0": 0, "p1": 1, "p2": 2, "p3": 3}[self._drag_handle]
                grasp.points[idx][0] += delta.x()
                grasp.points[idx][1] += delta.y()
                # Recompute opposite corner to maintain parallelogram
                if idx == 0:
                    grasp.points[3] = [
                        grasp.points[0][0] + grasp.points[2][0] - grasp.points[1][0],
                        grasp.points[0][1] + grasp.points[2][1] - grasp.points[1][1],
                    ]
                elif idx == 1:
                    grasp.points[3] = [
                        grasp.points[0][0] + grasp.points[2][0] - grasp.points[1][0],
                        grasp.points[0][1] + grasp.points[2][1] - grasp.points[1][1],
                    ]
                elif idx == 2:
                    grasp.points[3] = [
                        grasp.points[0][0] + grasp.points[2][0] - grasp.points[1][0],
                        grasp.points[0][1] + grasp.points[2][1] - grasp.points[1][1],
                    ]
                elif idx == 3:
                    pass  # p3 is derived, don't drag freely

            self._drag_item.update_geometry()

    def _end_drag(self, event):
        if self._dragging and self._annotation is not None:
            self.annotation_modified.emit()
        self._dragging = False
        self._drag_start = None
        self._drag_item = None
        self._drag_handle = None
        self._drag_original_bbox = None
        self._drag_original_grasp_pts = None

    def _update_select_hover(self, scene_pos):
        cursor = Qt.CursorShape.ArrowCursor
        if self._annotation is not None:
            # Check grasps first (higher z-order / priority)
            obj, grasp = self._annotation.find_grasp_at(scene_pos.x(), scene_pos.y(), threshold=12)
            if grasp is not None and obj is not None:
                key = (obj.instance_id, grasp.grasp_id)
                if key in self._grasp_items:
                    handle = self._grasp_items[key].handle_at(scene_pos)
                    if handle in ("p0", "p1", "p2", "p3"):
                        cursor = Qt.CursorShape.PointingHandCursor
                    elif handle == "rotate":
                        cursor = Qt.CursorShape.SizeAllCursor
                    elif handle == "body":
                        cursor = Qt.CursorShape.SizeAllCursor
            else:
                # Check bbox items
                for inst_id, item in self._bbox_items.items():
                    handle = item.handle_at(scene_pos)
                    if handle is not None:
                        if handle == "body":
                            cursor = Qt.CursorShape.SizeAllCursor
                        else:
                            cursor = Qt.CursorShape.PointingHandCursor
                        break

        self.setCursor(cursor)

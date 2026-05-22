"""Side panel — right-side widget with object list, grasp editor, export buttons."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QSplitter,
)

from assistive_grasp_annotator.models.annotation import (
    AnnotationModel,
    GraspAnnotation,
    ObjectAnnotation,
)
from assistive_grasp_annotator.models.classes import ClassRegistry


DIFFICULTY_LABELS = [
    ("easy", 1.0),
    ("medium", 0.7),
    ("hard", 0.4),
    ("invalid", 0.0),
]


class SidePanel(QWidget):
    """Right panel with image info, object list, class selector, grasp editor, export."""

    class_changed = Signal(int, int)            # instance_id, class_id
    object_delete_requested = Signal(int)        # instance_id
    grasp_delete_requested = Signal(int, int)    # instance_id, grasp_id
    difficulty_changed = Signal(int, int, str)   # instance_id, grasp_id, difficulty
    quality_changed = Signal(int, int, float)
    note_changed = Signal(int, int, str)
    add_grasp_requested = Signal(int)
    export_yolo_requested = Signal()
    export_grasp_roi_requested = Signal()
    object_selected = Signal(int)                # instance_id
    grasp_selected = Signal(int, int)            # instance_id, grasp_id
    mode_change_requested = Signal(str)           # 'bbox', 'grasp', 'select'

    def __init__(self, parent=None):
        super().__init__(parent)
        self._annotation: Optional[AnnotationModel] = None
        self._class_registry: Optional[ClassRegistry] = None
        self._selected_instance_id: Optional[int] = None
        self._selected_grasp_id: Optional[int] = None
        self._suppress_signals: bool = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # --- Image Info ---
        info_group = QGroupBox("Image Info")
        info_layout = QFormLayout(info_group)
        self._image_path_label = QLabel("")
        self._image_path_label.setWordWrap(True)
        self._image_size_label = QLabel("")
        self._annotated_label = QLabel("")
        info_layout.addRow("Path:", self._image_path_label)
        info_layout.addRow("Size:", self._image_size_label)
        info_layout.addRow("Objects:", self._annotated_label)
        layout.addWidget(info_group)

        # --- Mode Buttons ---
        mode_group = QGroupBox("Mode")
        mode_layout = QHBoxLayout(mode_group)
        self._select_btn = QPushButton("Select (V)")
        self._select_btn.setCheckable(True)
        self._select_btn.setChecked(True)
        self._bbox_btn = QPushButton("BBox (A)")
        self._bbox_btn.setCheckable(True)
        self._grasp_btn = QPushButton("Grasp (G)")
        self._grasp_btn.setCheckable(True)
        mode_layout.addWidget(self._select_btn)
        mode_layout.addWidget(self._bbox_btn)
        mode_layout.addWidget(self._grasp_btn)
        layout.addWidget(mode_group)

        self._select_btn.clicked.connect(lambda: self.mode_change_requested.emit("select"))
        self._bbox_btn.clicked.connect(lambda: self.mode_change_requested.emit("bbox"))
        self._grasp_btn.clicked.connect(lambda: self.mode_change_requested.emit("grasp"))

        # --- Objects ---
        obj_group = QGroupBox("Objects")
        obj_layout = QVBoxLayout(obj_group)

        self._object_list = QListWidget()
        self._object_list.setMaximumHeight(150)
        obj_layout.addWidget(self._object_list)

        cls_layout = QHBoxLayout()
        cls_layout.addWidget(QLabel("Class:"))
        self._class_combo = QComboBox()
        self._class_combo.setMinimumWidth(100)
        cls_layout.addWidget(self._class_combo, 1)
        obj_layout.addLayout(cls_layout)

        obj_btn_layout = QHBoxLayout()
        self._add_bbox_btn = QPushButton("Add BBox (A)")
        self._delete_obj_btn = QPushButton("Delete")
        obj_btn_layout.addWidget(self._add_bbox_btn)
        obj_btn_layout.addWidget(self._delete_obj_btn)
        obj_layout.addLayout(obj_btn_layout)
        layout.addWidget(obj_group)

        # --- Grasps ---
        grasp_group = QGroupBox("Grasps")
        grasp_layout = QVBoxLayout(grasp_group)

        self._grasp_list = QListWidget()
        self._grasp_list.setMaximumHeight(100)
        grasp_layout.addWidget(self._grasp_list)

        # Difficulty
        diff_layout = QHBoxLayout()
        diff_layout.addWidget(QLabel("Diff:"))
        self._diff_combo = QComboBox()
        for label, val in DIFFICULTY_LABELS:
            self._diff_combo.addItem(f"{label} ({val})", label)
        diff_layout.addWidget(self._diff_combo)
        grasp_layout.addLayout(diff_layout)

        # Quality
        qual_layout = QHBoxLayout()
        qual_layout.addWidget(QLabel("Qual:"))
        self._quality_spin = QDoubleSpinBox()
        self._quality_spin.setRange(0.0, 1.0)
        self._quality_spin.setSingleStep(0.05)
        self._quality_spin.setDecimals(2)
        qual_layout.addWidget(self._quality_spin)
        grasp_layout.addLayout(qual_layout)

        # Note
        note_layout = QVBoxLayout()
        note_layout.addWidget(QLabel("Note:"))
        self._note_edit = QTextEdit()
        self._note_edit.setMaximumHeight(60)
        self._note_edit.setPlaceholderText("e.g. middle cross grasp")
        note_layout.addWidget(self._note_edit)
        grasp_layout.addLayout(note_layout)

        grasp_btn_layout = QHBoxLayout()
        self._add_grasp_btn = QPushButton("Add Grasp (G)")
        self._delete_grasp_btn = QPushButton("Delete")
        grasp_btn_layout.addWidget(self._add_grasp_btn)
        grasp_btn_layout.addWidget(self._delete_grasp_btn)
        grasp_layout.addLayout(grasp_btn_layout)
        layout.addWidget(grasp_group)

        # --- Export ---
        export_group = QGroupBox("Export")
        export_layout = QVBoxLayout(export_group)
        self._export_yolo_btn = QPushButton("Export YOLO Labels")
        self._export_roi_btn = QPushButton("Export Grasp ROIs")
        export_layout.addWidget(self._export_yolo_btn)
        export_layout.addWidget(self._export_roi_btn)
        layout.addWidget(export_group)

        layout.addStretch()

        # --- Connections ---
        self._object_list.currentRowChanged.connect(self._on_object_row_changed)
        self._grasp_list.currentRowChanged.connect(self._on_grasp_row_changed)
        self._class_combo.currentIndexChanged.connect(self._on_class_combo_changed)
        self._diff_combo.currentIndexChanged.connect(self._on_difficulty_changed)
        self._quality_spin.valueChanged.connect(self._on_quality_changed)
        self._note_edit.textChanged.connect(self._on_note_changed)

        self._add_bbox_btn.clicked.connect(lambda: self.mode_change_requested.emit("bbox"))
        self._add_grasp_btn.clicked.connect(lambda: self.mode_change_requested.emit("grasp"))
        self._delete_obj_btn.clicked.connect(self._on_delete_object)
        self._delete_grasp_btn.clicked.connect(self._on_delete_grasp)

        self._export_yolo_btn.clicked.connect(self.export_yolo_requested.emit)
        self._export_roi_btn.clicked.connect(self.export_grasp_roi_requested.emit)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_annotation(self, annotation: Optional[AnnotationModel]):
        """Full reset — used when switching images."""
        self._annotation = annotation
        self._selected_instance_id = None
        self._selected_grasp_id = None
        self._refresh_all()

    def refresh_data(self):
        """Refresh object/grasp lists without losing current selection."""
        if self._annotation is None:
            return
        saved_obj = self._selected_instance_id
        saved_grasp = self._selected_grasp_id

        self._suppress_signals = True
        self._refresh_image_info()
        self._refresh_object_list()
        self._refresh_grasp_list()

        # Restore selection from saved state
        if saved_obj is not None:
            obj = self._annotation.get_object_by_instance(saved_obj)
            if obj is not None:
                self._selected_instance_id = saved_obj
                for row in range(self._object_list.count()):
                    item = self._object_list.item(row)
                    if item is not None and item.data(Qt.ItemDataRole.UserRole) == saved_obj:
                        self._object_list.setCurrentRow(row)
                        break
                else:
                    self._selected_instance_id = None
                    self._selected_grasp_id = None
            else:
                self._selected_instance_id = None
                self._selected_grasp_id = None

            if saved_grasp is not None and self._selected_instance_id is not None:
                for row in range(self._grasp_list.count()):
                    item = self._grasp_list.item(row)
                    if item is not None and item.data(Qt.ItemDataRole.UserRole) == saved_grasp:
                        self._grasp_list.setCurrentRow(row)
                        break
        else:
            self._selected_grasp_id = None

        self._suppress_signals = False

    def set_class_registry(self, registry: Optional[ClassRegistry]):
        self._class_registry = registry
        self._suppress_signals = True
        self._class_combo.clear()
        if registry is not None:
            for cls in registry.all_classes():
                label = f"{cls.name} (id={cls.id})"
                self._class_combo.addItem(label, cls.id)
        self._suppress_signals = False

    def select_object(self, obj: Optional[ObjectAnnotation]):
        self._selected_instance_id = obj.instance_id if obj else None
        self._selected_grasp_id = None
        self._suppress_signals = True

        # Update object list selection
        if obj is not None:
            for row in range(self._object_list.count()):
                item = self._object_list.item(row)
                if item is not None:
                    data = item.data(Qt.ItemDataRole.UserRole)
                    if data == obj.instance_id:
                        self._object_list.setCurrentRow(row)
                        break

            # Update class combo
            idx = self._class_combo.findData(obj.class_id)
            if idx >= 0:
                self._class_combo.setCurrentIndex(idx)

        self._refresh_grasp_list()
        self._suppress_signals = False

    def select_grasp(self, grasp: Optional[GraspAnnotation]):
        self._selected_grasp_id = grasp.grasp_id if grasp else None
        self._suppress_signals = True

        if grasp is not None:
            for row in range(self._grasp_list.count()):
                item = self._grasp_list.item(row)
                if item is not None:
                    data = item.data(Qt.ItemDataRole.UserRole)
                    if data == grasp.grasp_id:
                        self._grasp_list.setCurrentRow(row)
                        break
            self._update_grasp_editors(grasp)

        self._suppress_signals = False

    def set_mode_buttons(self, mode: str):
        self._select_btn.setChecked(mode == "select")
        self._bbox_btn.setChecked(mode == "bbox")
        self._grasp_btn.setChecked(mode == "grasp")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refresh_all(self):
        self._suppress_signals = True
        self._refresh_image_info()
        self._refresh_object_list()
        self._refresh_grasp_list()
        self._suppress_signals = False

    def _refresh_image_info(self):
        if self._annotation is None:
            self._image_path_label.setText("")
            self._image_size_label.setText("")
            self._annotated_label.setText("")
            return
        path = str(self._annotation.image_path or "")
        if len(path) > 80:
            path = "..." + path[-77:]
        self._image_path_label.setText(path)
        if self._annotation.image_size:
            w, h = self._annotation.image_size
            self._image_size_label.setText(f"{w} x {h}")
        n_obj = len(self._annotation.objects)
        n_grasp = self._annotation.grasp_count()
        self._annotated_label.setText(f"{n_obj} objects, {n_grasp} grasps")

    def _refresh_object_list(self):
        self._object_list.clear()
        if self._annotation is None:
            return
        for obj in self._annotation.objects:
            label = f"[{obj.instance_id}] {obj.class_name or f'class_{obj.class_id}'}"
            if not obj.graspable:
                label += " (r/o)"
            if obj.grasps:
                label += f" +{len(obj.grasps)}g"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, obj.instance_id)
            self._object_list.addItem(item)

    def _refresh_grasp_list(self):
        self._grasp_list.clear()
        if self._annotation is None or self._selected_instance_id is None:
            self._clear_grasp_editors()
            return
        obj = self._annotation.get_object_by_instance(self._selected_instance_id)
        if obj is None:
            self._clear_grasp_editors()
            return
        for grasp in obj.grasps:
            label = f"[G{grasp.grasp_id}] {grasp.difficulty} q={grasp.quality:.1f}"
            if grasp.note:
                label += f" — {grasp.note[:20]}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, grasp.grasp_id)
            self._grasp_list.addItem(item)

    def _update_grasp_editors(self, grasp: GraspAnnotation):
        idx = self._diff_combo.findData(grasp.difficulty)
        if idx >= 0:
            self._diff_combo.setCurrentIndex(idx)
        self._quality_spin.setValue(grasp.quality)
        self._note_edit.setPlainText(grasp.note)

    def _clear_grasp_editors(self):
        self._diff_combo.setCurrentIndex(0)
        self._quality_spin.setValue(1.0)
        self._note_edit.setPlainText("")

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_object_row_changed(self, row: int):
        if self._suppress_signals:
            return
        item = self._object_list.item(row)
        if item is None:
            return
        instance_id = item.data(Qt.ItemDataRole.UserRole)
        if instance_id is not None:
            self.object_selected.emit(instance_id)

    def _on_grasp_row_changed(self, row: int):
        if self._suppress_signals:
            return
        item = self._grasp_list.item(row)
        if item is None:
            return
        grasp_id = item.data(Qt.ItemDataRole.UserRole)
        if grasp_id is not None and self._selected_instance_id is not None:
            self.grasp_selected.emit(self._selected_instance_id, grasp_id)

    def _on_class_combo_changed(self, index: int):
        if self._suppress_signals or self._selected_instance_id is None:
            return
        class_id = self._class_combo.itemData(index)
        if class_id is not None:
            self.class_changed.emit(self._selected_instance_id, class_id)

    def _on_difficulty_changed(self, index: int):
        if self._suppress_signals or self._selected_instance_id is None or self._selected_grasp_id is None:
            return
        difficulty = self._diff_combo.itemData(index)
        if difficulty is not None:
            self.difficulty_changed.emit(
                self._selected_instance_id, self._selected_grasp_id, difficulty)

    def _on_quality_changed(self, value: float):
        if self._suppress_signals or self._selected_instance_id is None or self._selected_grasp_id is None:
            return
        self.quality_changed.emit(self._selected_instance_id, self._selected_grasp_id, value)

    def _on_note_changed(self):
        if self._suppress_signals or self._selected_instance_id is None or self._selected_grasp_id is None:
            return
        self.note_changed.emit(
            self._selected_instance_id, self._selected_grasp_id,
            self._note_edit.toPlainText())

    def _on_delete_object(self):
        if self._selected_instance_id is not None:
            self.object_delete_requested.emit(self._selected_instance_id)

    def _on_delete_grasp(self):
        if self._selected_instance_id is not None and self._selected_grasp_id is not None:
            self.grasp_delete_requested.emit(self._selected_instance_id, self._selected_grasp_id)

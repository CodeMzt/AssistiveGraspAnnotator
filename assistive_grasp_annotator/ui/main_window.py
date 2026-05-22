"""Main window — application shell orchestrating all components."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from assistive_grasp_annotator.models.annotation import AnnotationModel, GraspAnnotation, ObjectAnnotation
from assistive_grasp_annotator.models.classes import ClassRegistry
from assistive_grasp_annotator.models.dataset import DatasetModel
from assistive_grasp_annotator.ui.class_editor import ClassEditorDialog
from assistive_grasp_annotator.ui.dataset_wizard import DatasetWizard
from assistive_grasp_annotator.ui.image_canvas import CanvasMode, ImageCanvas
from assistive_grasp_annotator.ui.side_panel import SidePanel
from assistive_grasp_annotator.tools.validators import validate_annotation


class MainWindow(QMainWindow):
    """Top-level application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Assistive Grasp Annotator")
        self.resize(1600, 950)

        self._dataset = DatasetModel(self)
        self._class_registry: Optional[ClassRegistry] = None

        self._setup_ui()
        self._setup_menu_bar()
        self._setup_status_bar()
        self._setup_shortcuts()
        self._connect_signals()

        self._current_annotation: Optional[AnnotationModel] = None
        self._dirty: bool = False

        self._update_title()

        self.setAcceptDrops(True)

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel — image list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(2, 2, 2, 2)
        left_layout.addWidget(QLabel("Images"))
        self._image_list = QListWidget()
        self._image_list.setMinimumWidth(180)
        self._image_list.setMaximumWidth(300)
        left_layout.addWidget(self._image_list)
        splitter.addWidget(left_panel)

        # Center — canvas
        self._canvas = ImageCanvas()
        splitter.addWidget(self._canvas)

        # Right — side panel
        self._side_panel = SidePanel()
        self._side_panel.setMinimumWidth(260)
        self._side_panel.setMaximumWidth(380)
        splitter.addWidget(self._side_panel)

        splitter.setSizes([200, 1000, 280])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

        self.setCentralWidget(splitter)

    def _setup_menu_bar(self):
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu("&File")
        file_menu.addAction("&New Dataset...", self._new_dataset, QKeySequence("Ctrl+N"))
        file_menu.addAction("&Open Dataset...", self._open_dataset, QKeySequence("Ctrl+O"))
        file_menu.addSeparator()
        file_menu.addAction("&Save", self._save, QKeySequence("Ctrl+S"))
        file_menu.addAction("Save &All", self._save_all, QKeySequence("Ctrl+Shift+S"))
        file_menu.addSeparator()
        file_menu.addAction("&Edit Classes...", self._edit_classes)
        file_menu.addSeparator()
        file_menu.addAction("&Close Dataset", self._close_dataset)
        file_menu.addSeparator()
        file_menu.addAction("E&xit", self.close, QKeySequence("Alt+F4"))

        # View
        view_menu = mb.addMenu("&View")
        view_menu.addAction("Zoom &In", self._canvas.zoom_in, QKeySequence("Ctrl++"))
        view_menu.addAction("Zoom &Out", self._canvas.zoom_out, QKeySequence("Ctrl+-"))
        view_menu.addAction("Zoom to &Fit", self._canvas.zoom_to_fit, QKeySequence("Ctrl+0"))
        view_menu.addAction("&Original Size", self._canvas.zoom_original, QKeySequence("Ctrl+1"))

        # Mode
        mode_menu = mb.addMenu("&Mode")
        act_select = mode_menu.addAction("&Select (V)", lambda: self._canvas.set_mode(CanvasMode.SELECT))
        act_select.setShortcut(QKeySequence("V"))
        act_bbox = mode_menu.addAction("&BBox (A)", lambda: self._canvas.set_mode(CanvasMode.BBOX))
        act_bbox.setShortcut(QKeySequence("A"))
        act_grasp = mode_menu.addAction("&Grasp (G)", lambda: self._canvas.set_mode(CanvasMode.GRASP))
        act_grasp.setShortcut(QKeySequence("G"))

        # Export
        export_menu = mb.addMenu("&Export")
        export_menu.addAction("Export YOLO &Labels...", self._export_yolo)
        export_menu.addAction("Export Grasp &ROIs...", self._export_grasp_roi)
        export_menu.addAction("Export &Target Maps (.npz)...", self._export_target_maps)

        # Validate
        validate_menu = mb.addMenu("&Validate")
        validate_menu.addAction("Validate &Current", self._validate_current)
        validate_menu.addAction("Validate &All", self._validate_all)

        # Help
        help_menu = mb.addMenu("&Help")
        help_menu.addAction("&Keyboard Shortcuts...", self._show_shortcuts)
        help_menu.addAction("&About", self._show_about)

    def _setup_status_bar(self):
        self._mode_label = QLabel("Mode: Select")
        self._coord_label = QLabel("")
        self._counter_label = QLabel("0 / 0")
        self._save_label = QLabel("")

        sb = self.statusBar()
        sb.addWidget(self._mode_label)
        sb.addWidget(self._coord_label, 1)
        sb.addPermanentWidget(self._counter_label)
        sb.addPermanentWidget(self._save_label)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("N"), self, self._next_image)
        QShortcut(QKeySequence("Right"), self, self._next_image)
        QShortcut(QKeySequence("P"), self, self._prev_image)
        QShortcut(QKeySequence("Left"), self, self._prev_image)
        QShortcut(QKeySequence("Delete"), self, self._canvas.delete_selected)
        QShortcut(QKeySequence("Backspace"), self, self._canvas.delete_selected)
        QShortcut(QKeySequence("1"), self, lambda: self._set_difficulty("easy"))
        QShortcut(QKeySequence("2"), self, lambda: self._set_difficulty("medium"))
        QShortcut(QKeySequence("3"), self, lambda: self._set_difficulty("hard"))
        QShortcut(QKeySequence("4"), self, lambda: self._set_difficulty("invalid"))
        QShortcut(QKeySequence("Escape"), self, self._cancel_or_clear_selection)

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self):
        self._dataset.dataset_opened.connect(self._on_dataset_opened)
        self._dataset.dataset_closed.connect(self._on_dataset_closed)
        self._dataset.current_image_changed.connect(self._on_image_changed)
        self._dataset.image_list_changed.connect(self._on_image_list_changed)

        self._image_list.currentRowChanged.connect(self._on_image_list_selection)

        self._canvas.mode_changed.connect(self._on_canvas_mode_changed)
        self._canvas.mouse_position_changed.connect(self._on_mouse_moved)
        self._canvas.annotation_modified.connect(self._on_annotation_modified)
        self._canvas.selection_changed.connect(self._on_canvas_selection_changed)
        self._canvas.no_object_for_grasp.connect(self._on_no_object_for_grasp)

        self._side_panel.object_selected.connect(self._on_panel_object_selected)
        self._side_panel.grasp_selected.connect(self._on_panel_grasp_selected)
        self._side_panel.class_changed.connect(self._on_class_changed)
        self._side_panel.object_delete_requested.connect(self._on_delete_object)
        self._side_panel.grasp_delete_requested.connect(self._on_delete_grasp)
        self._side_panel.difficulty_changed.connect(self._on_difficulty_changed)
        self._side_panel.quality_changed.connect(self._on_quality_changed)
        self._side_panel.note_changed.connect(self._on_note_changed)
        self._side_panel.mode_change_requested.connect(self._on_mode_change_requested)
        self._side_panel.export_yolo_requested.connect(self._export_yolo)
        self._side_panel.export_grasp_roi_requested.connect(self._export_grasp_roi)

    # ------------------------------------------------------------------
    # Slots — Dataset
    # ------------------------------------------------------------------

    def _new_dataset(self):
        wizard = DatasetWizard(self)
        wizard.dataset_created.connect(self._on_dataset_created)
        wizard.exec()

    def _on_dataset_created(self, dataset_path: str):
        success = self._dataset.open_dataset(dataset_path)
        if not success:
            QMessageBox.warning(self, "Error",
                                f"Dataset structure was created but could not be opened:\n{dataset_path}")

    def _edit_classes(self):
        if self._dataset.dataset_path is None:
            QMessageBox.information(self, "No Dataset",
                                    "Open a dataset first before editing classes.")
            return

        dlg = ClassEditorDialog(self)
        classes_yaml = self._dataset.dataset_path / "classes.yaml"
        if classes_yaml.exists():
            dlg.load_from_yaml(classes_yaml)
        elif self._class_registry is not None:
            # Seed from current registry
            classes = [c.to_dict() for c in self._class_registry.all_classes()]
            dlg.set_class_list(classes)

        if dlg.exec() == ClassEditorDialog.DialogCode.Accepted:
            dlg.save_to_yaml(classes_yaml)
            # Reload
            from assistive_grasp_annotator.models.classes import ClassRegistry
            if classes_yaml.exists():
                self._class_registry = ClassRegistry.from_yaml(classes_yaml)
                self._dataset._classes = self._class_registry
                self._side_panel.set_class_registry(self._class_registry)

    def _open_dataset(self):
        path = QFileDialog.getExistingDirectory(self, "Open Dataset Directory")
        if not path:
            return
        success = self._dataset.open_dataset(path)
        if not success:
            QMessageBox.warning(self, "Error",
                                f"Could not open dataset at {path}.\n\n"
                                "A dataset needs at least some image files.\n\n"
                                "If you have a folder of images, use File → New Dataset... instead.")

    def _close_dataset(self):
        if self._dirty:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "There are unsaved changes. Save before closing?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Save:
                self._save_all()
            elif reply == QMessageBox.StandardButton.Cancel:
                return
        self._dataset.close_dataset()

    def _on_dataset_opened(self):
        self._class_registry = self._dataset.class_registry
        self._side_panel.set_class_registry(self._class_registry)
        self._rebuild_image_list()
        self._update_title()

    def _on_dataset_closed(self):
        self._canvas.load_image_and_annotation("", AnnotationModel())
        self._side_panel.set_annotation(None)
        self._image_list.clear()
        self._class_registry = None
        self._current_annotation = None
        self._dirty = False
        self._update_title()

    def _on_image_list_changed(self):
        self._rebuild_image_list()

    def _on_image_changed(self, image_key: str, annotation: AnnotationModel):
        self._current_annotation = annotation
        self._dirty = annotation.dirty
        img_path = self._dataset.current_image_path
        if img_path is not None:
            self._canvas.load_image_and_annotation(img_path, annotation, self._class_registry)
        self._side_panel.set_annotation(annotation)
        self._update_status_info()
        self._sync_image_list_selection()

    # ------------------------------------------------------------------
    # Slots — Image list
    # ------------------------------------------------------------------

    def _rebuild_image_list(self):
        self._image_list.clear()
        for img_path in self._dataset.image_paths:
            key = self._dataset._make_image_key(img_path)
            item = QListWidgetItem(str(key))
            item.setData(Qt.ItemDataRole.UserRole, key)
            self._image_list.addItem(item)

    def _on_image_list_selection(self, row: int):
        if row < 0:
            return
        item = self._image_list.item(row)
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        for i, img_path in enumerate(self._dataset.image_paths):
            if self._dataset._make_image_key(img_path) == key:
                if self._dataset.select_image(i):
                    self._image_list.setCurrentRow(i)
                break

    # ------------------------------------------------------------------
    # Slots — Canvas
    # ------------------------------------------------------------------

    def _on_canvas_mode_changed(self, mode: CanvasMode):
        label = f"Mode: {mode.name.capitalize()}"
        self._mode_label.setText(label)
        mode_str = mode.name.lower()
        self._side_panel.set_mode_buttons(mode_str)

    def _on_mouse_moved(self, x: float, y: float):
        self._coord_label.setText(f"({x:.0f}, {y:.0f})")

    def _on_annotation_modified(self):
        self._dirty = True
        if self._current_annotation is not None:
            self._current_annotation.dirty = True
        self._update_title()
        self._update_status_info()
        # Targeted refresh — preserves user's selection
        self._side_panel.refresh_data()

    def _on_canvas_selection_changed(self, obj, grasp):
        self._side_panel.select_object(obj)
        if obj is not None and grasp is not None:
            self._side_panel.select_grasp(grasp)

    def _on_no_object_for_grasp(self):
        self._save_label.setText("Draw a bbox first (A), then select it before drawing grasps (G)")

    # ------------------------------------------------------------------
    # Slots — Side panel
    # ------------------------------------------------------------------

    def _on_panel_object_selected(self, instance_id: int):
        if self._current_annotation is None:
            return
        obj = self._current_annotation.get_object_by_instance(instance_id)
        if obj is not None:
            self._canvas.select_object(obj)

    def _on_panel_grasp_selected(self, instance_id: int, grasp_id: int):
        if self._current_annotation is None:
            return
        obj = self._current_annotation.get_object_by_instance(instance_id)
        grasp = self._current_annotation.get_grasp(instance_id, grasp_id)
        if obj is not None and grasp is not None:
            self._canvas.select_grasp(obj, grasp)

    def _on_class_changed(self, instance_id: int, class_id: int):
        if self._current_annotation is None or self._class_registry is None:
            return
        cls = self._class_registry.get_class(class_id)
        if cls is not None:
            self._current_annotation.update_object_class(
                instance_id, cls.id, cls.name, cls.graspable, cls.policy)
            self._canvas._redraw_all_items()
            self._side_panel.refresh_data()

    def _on_delete_object(self, instance_id: int):
        if self._current_annotation is None:
            return
        # Clear canvas selection before deleting
        self._canvas._selected_obj = None
        self._canvas._selected_grasp = None
        self._current_annotation.remove_object(instance_id)
        self._canvas._redraw_all_items()
        self._side_panel.refresh_data()
        self._dirty = True
        self._update_title()
        self._update_status_info()

    def _on_delete_grasp(self, instance_id: int, grasp_id: int):
        if self._current_annotation is None:
            return
        # Clear canvas selection if this grasp was selected
        if (self._canvas._selected_obj is not None and
            self._canvas._selected_obj.instance_id == instance_id and
            self._canvas._selected_grasp is not None and
            self._canvas._selected_grasp.grasp_id == grasp_id):
            self._canvas._selected_grasp = None
        self._current_annotation.remove_grasp(instance_id, grasp_id)
        self._canvas._redraw_all_items()
        self._side_panel.refresh_data()
        self._dirty = True
        self._update_title()
        self._update_status_info()

    def _on_difficulty_changed(self, instance_id: int, grasp_id: int, difficulty: str):
        if self._current_annotation is None:
            return
        self._current_annotation.update_grasp_metadata(
            instance_id, grasp_id, difficulty=difficulty)
        self._canvas._redraw_all_items()
        self._side_panel.refresh_data()

    def _on_quality_changed(self, instance_id: int, grasp_id: int, quality: float):
        if self._current_annotation is None:
            return
        self._current_annotation.update_grasp_metadata(
            instance_id, grasp_id, quality=quality)
        self._canvas._redraw_all_items()
        self._side_panel.refresh_data()

    def _on_note_changed(self, instance_id: int, grasp_id: int, note: str):
        if self._current_annotation is None:
            return
        self._current_annotation.update_grasp_metadata(
            instance_id, grasp_id, note=note)
        self._side_panel.refresh_data()

    def _on_mode_change_requested(self, mode: str):
        mode_map = {
            "select": CanvasMode.SELECT,
            "bbox": CanvasMode.BBOX,
            "grasp": CanvasMode.GRASP,
        }
        if mode in mode_map:
            self._canvas.set_mode(mode_map[mode])

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _next_image(self):
        self._save_if_dirty()
        if self._dataset.next_image():
            self._sync_image_list_selection()

    def _prev_image(self):
        self._save_if_dirty()
        if self._dataset.prev_image():
            self._sync_image_list_selection()

    def _sync_image_list_selection(self):
        self._image_list.blockSignals(True)
        self._image_list.setCurrentRow(self._dataset.current_index)
        self._image_list.blockSignals(False)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save(self):
        if self._dataset.save_current_annotation():
            self._dirty = False
            self._save_label.setText("Saved")
            self._update_title()
        else:
            self._save_label.setText("No dataset open")

    def _save_all(self):
        saved, errors = self._dataset.save_all_annotations()
        self._dirty = False
        self._update_title()
        QMessageBox.information(self, "Save All", f"Saved {saved} annotation(s)." +
                                (f" {errors} error(s)." if errors else ""))

    def _save_if_dirty(self):
        if self._dirty:
            self._dataset.save_current_annotation()
            self._dirty = False
            self._update_title()
            self._save_label.setText("Saved")

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _export_yolo(self):
        from assistive_grasp_annotator.tools.export_yolo import export_yolo_labels
        default_dir = ""
        if self._dataset.dataset_path is not None:
            default_dir = str(self._dataset.dataset_path / "generated" / "detector_yolo")
        out_dir = QFileDialog.getExistingDirectory(self, "Select Output Directory for YOLO Labels", default_dir)
        if not out_dir:
            return
        count, errors = export_yolo_labels(self._dataset, out_dir)
        QMessageBox.information(self, "Export Completed",
                                f"Exported {count} YOLO label file(s)." +
                                (f" {errors} error(s)." if errors else ""))

    def _export_grasp_roi(self):
        from assistive_grasp_annotator.tools.export_grasp_roi import export_grasp_rois
        default_dir = ""
        if self._dataset.dataset_path is not None:
            default_dir = str(self._dataset.dataset_path / "generated" / "grasp_roi")
        out_dir = QFileDialog.getExistingDirectory(self, "Select Output Directory for Grasp ROIs", default_dir)
        if not out_dir:
            return
        count, errors = export_grasp_rois(self._dataset, out_dir)
        QMessageBox.information(self, "Export Completed",
                                f"Exported {count} grasp ROI(s)." +
                                (f" {errors} error(s)." if errors else ""))

    def _export_target_maps(self):
        from assistive_grasp_annotator.tools.export_target_maps import export_target_maps
        default_dir = ""
        if self._dataset.dataset_path is not None:
            default_dir = str(self._dataset.dataset_path / "generated" / "target_maps")
        out_dir = QFileDialog.getExistingDirectory(self, "Select Output Directory for Target Maps", default_dir)
        if not out_dir:
            return
        count, errors = export_target_maps(self._dataset, out_dir)
        QMessageBox.information(self, "Export Completed",
                                f"Exported {count} target map set(s)." +
                                (f" {errors} error(s)." if errors else ""))

    # ------------------------------------------------------------------
    # Validate
    # ------------------------------------------------------------------

    def _validate_current(self):
        if self._current_annotation is None:
            return
        errors = validate_annotation(self._current_annotation, self._class_registry)
        if not errors:
            QMessageBox.information(self, "Validation", "No issues found.")
        else:
            QMessageBox.warning(self, "Validation Issues",
                                f"Found {len(errors)} issue(s):\n\n" +
                                "\n".join(errors[:20]))

    def _validate_all(self):
        all_errors: list[str] = []
        for img_path in self._dataset.image_paths:
            ann = self._dataset.load_annotation(img_path)
            errs = validate_annotation(ann, self._class_registry)
            key = self._dataset._make_image_key(img_path)
            for e in errs:
                all_errors.append(f"{key}: {e}")
        if not all_errors:
            QMessageBox.information(self, "Validation", "All annotations pass validation.")
        else:
            QMessageBox.warning(self, "Validation Issues",
                                f"Found {len(all_errors)} issue(s):\n\n" +
                                "\n".join(all_errors[:30]))

    # ------------------------------------------------------------------
    # Shortcuts
    # ------------------------------------------------------------------

    def _set_difficulty(self, difficulty: str):
        if self._current_annotation is None:
            return
        obj = self._canvas._selected_obj
        grasp = self._canvas._selected_grasp
        if obj is not None and grasp is not None:
            self._current_annotation.update_grasp_metadata(
                obj.instance_id, grasp.grasp_id, difficulty=difficulty)
            self._canvas._redraw_all_items()
            self._side_panel.refresh_data()

    def _cancel_or_clear_selection(self):
        self._canvas._cancel_drawing()
        self._canvas.set_mode(CanvasMode.SELECT)
        self._canvas.select_object(None)

    # ------------------------------------------------------------------
    # Title & Status
    # ------------------------------------------------------------------

    def _update_title(self):
        title = "Assistive Grasp Annotator"
        if self._dataset.dataset_path is not None:
            title += f" — {self._dataset.dataset_path.name}"
        if self._dirty:
            title += " *"
        self.setWindowTitle(title)

    def _update_status_info(self):
        idx = self._dataset.current_index
        total = self._dataset.image_count
        self._counter_label.setText(f"{idx + 1} / {total}" if total > 0 else "0 / 0")
        self._save_label.setText("Unsaved" if self._dirty else "")

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _show_shortcuts(self):
        text = """\
Keyboard Shortcuts:
  Ctrl+O      Open dataset directory
  Ctrl+S      Save current annotation
  Ctrl+Shift+S Save all annotations
  A           BBox mode — click & drag to draw
  G           Grasp mode — 3 clicks to draw
  V           Select mode — move/resize items
  Delete      Delete selected object or grasp
  N / →       Next image
  P / ←       Previous image
  1 / 2 / 3 / 4  Set difficulty: easy/medium/hard/invalid
  Esc         Cancel drawing / deselect
  Ctrl++      Zoom in
  Ctrl+-      Zoom out
  Ctrl+0      Zoom to fit
  Scroll      Zoom in/out
  Space+drag  Pan image"""
        QMessageBox.information(self, "Keyboard Shortcuts", text)

    def _show_about(self):
        QMessageBox.about(
            self, "About",
            "Assistive Grasp Annotator\n\n"
            "Desktop annotation tool for assistive grasping datasets.\n"
            "Labels object bboxes + grasp rectangles for two-stage "
            "semantic detection + grasp prediction pipeline.")

    def closeEvent(self, event):
        if self._dirty:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "Save changes before exiting?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Save:
                self._save_all()
                event.accept()
            elif reply == QMessageBox.StandardButton.Discard:
                event.accept()
            else:
                event.ignore()
                return
        super().closeEvent(event)

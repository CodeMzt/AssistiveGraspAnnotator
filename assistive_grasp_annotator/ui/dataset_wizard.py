"""Dataset creation wizard — guides user through creating a dataset from raw images."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from assistive_grasp_annotator.ui.class_editor import ClassEditorWidget


class DatasetWizard(QDialog):
    """Wizard dialog for creating a new dataset from a folder of raw images."""

    dataset_created = Signal(str)  # dataset root path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Dataset")
        self.resize(700, 600)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # --- Step 1: Image Source ---
        src_group = QGroupBox("1. Image Source")
        src_layout = QFormLayout(src_group)

        # Source folder
        src_row = QHBoxLayout()
        self._src_edit = QLineEdit()
        self._src_edit.setPlaceholderText("Select folder with raw images...")
        self._src_edit.setReadOnly(True)
        src_row.addWidget(self._src_edit)
        src_browse = QPushButton("Browse...")
        src_browse.clicked.connect(self._browse_source)
        src_row.addWidget(src_browse)
        src_layout.addRow("Images folder:", src_row)
        layout.addWidget(src_group)

        # --- Step 2: Mode ---
        mode_group = QGroupBox("2. Storage Mode")
        mode_layout = QVBoxLayout(mode_group)

        self._inplace_radio = QRadioButton("In-place — use images where they are, create dataset files alongside")
        self._copy_radio = QRadioButton("Copy — copy images into a new dataset directory")
        self._inplace_radio.setChecked(True)
        mode_layout.addWidget(self._inplace_radio)

        copy_row = QHBoxLayout()
        copy_row.addWidget(self._copy_radio)
        self._dest_edit = QLineEdit()
        self._dest_edit.setPlaceholderText("Select destination directory...")
        self._dest_edit.setReadOnly(True)
        self._dest_edit.setEnabled(False)
        copy_row.addWidget(self._dest_edit)
        dest_browse = QPushButton("Browse...")
        dest_browse.clicked.connect(self._browse_dest)
        dest_browse.setEnabled(False)
        copy_row.addWidget(dest_browse)
        mode_layout.addLayout(copy_row)

        self._inplace_radio.toggled.connect(lambda checked: self._dest_edit.setEnabled(not checked))
        self._inplace_radio.toggled.connect(lambda checked: dest_browse.setEnabled(not checked))
        layout.addWidget(mode_group)

        # --- Step 3: Camera name ---
        cam_group = QGroupBox("3. Camera Subdirectory")
        cam_layout = QFormLayout(cam_group)
        self._camera_edit = QLineEdit("camera_1")
        cam_layout.addRow("Camera name:", self._camera_edit)
        layout.addWidget(cam_group)

        # --- Step 4: Classes ---
        cls_group = QGroupBox("4. Object Classes")
        cls_layout = QVBoxLayout(cls_group)
        cls_layout.addWidget(QLabel("Define the object classes for this dataset:"))
        self._class_editor = ClassEditorWidget(self)
        cls_layout.addWidget(self._class_editor)
        layout.addWidget(cls_group)

        # --- Buttons ---
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create Dataset")
        self._buttons.accepted.connect(self._on_create)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _browse_source(self):
        path = QFileDialog.getExistingDirectory(self, "Select Image Source Folder")
        if path:
            self._src_edit.setText(path)

    def _browse_dest(self):
        path = QFileDialog.getExistingDirectory(self, "Select Dataset Root Directory")
        if path:
            self._dest_edit.setText(path)

    def _on_create(self):
        src = self._src_edit.text().strip()
        if not src:
            QMessageBox.warning(self, "Missing Input", "Please select an image source folder.")
            return

        src_path = Path(src)
        if not src_path.is_dir():
            QMessageBox.warning(self, "Invalid Folder", f"Source folder does not exist:\n{src}")
            return

        # Find images in source
        img_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
        images = []
        for ext in img_exts:
            images.extend(src_path.rglob(f"*{ext}"))
            images.extend(src_path.rglob(f"*{ext.upper()}"))
        images = sorted(set(images))

        if not images:
            QMessageBox.warning(self, "No Images",
                                f"No image files found in:\n{src}\n\n"
                                "Supported: .jpg, .jpeg, .png, .bmp, .tiff")
            return

        camera_name = self._camera_edit.text().strip() or "camera_1"

        if self._inplace_radio.isChecked():
            dataset_root = src_path
            images_dir = dataset_root / "images" / camera_name
            images_dir.mkdir(parents=True, exist_ok=True)
            # Move/copy images into the images/camera/ structure
            for img in images:
                dst = images_dir / img.name
                if img.parent == images_dir or img.resolve() == dst.resolve():
                    continue
                if not dst.exists():
                    try:
                        os.replace(str(img), str(dst))
                    except OSError:
                        shutil.copy2(str(img), str(dst))
        else:
            dest = self._dest_edit.text().strip()
            if not dest:
                QMessageBox.warning(self, "Missing Input",
                                    "Please select a destination directory for copy mode.")
                return
            dataset_root = Path(dest)
            images_dir = dataset_root / "images" / camera_name
            images_dir.mkdir(parents=True, exist_ok=True)
            # Copy images
            i = 1
            for img in images:
                ext = img.suffix.lower()
                dst = images_dir / f"{i:06d}{ext}"
                while dst.exists():
                    i += 1
                    dst = images_dir / f"{i:06d}{ext}"
                shutil.copy2(str(img), str(dst))
                i += 1

        # Create other directories
        (dataset_root / "annotations").mkdir(parents=True, exist_ok=True)
        (dataset_root / "splits").mkdir(parents=True, exist_ok=True)
        (dataset_root / "generated").mkdir(parents=True, exist_ok=True)

        # Save classes.yaml
        classes_yaml = dataset_root / "classes.yaml"
        if not classes_yaml.exists() or self._class_editor.dirty:
            self._class_editor.save_to_yaml(classes_yaml)

        QMessageBox.information(
            self, "Dataset Created",
            f"Dataset created successfully at:\n{dataset_root}\n\n"
            f"Images: {len(images)}\n"
            f"Camera: {camera_name}\n"
            f"Classes: {len(self._class_editor.to_class_list())}"
        )

        self.dataset_created.emit(str(dataset_root))
        self.accept()

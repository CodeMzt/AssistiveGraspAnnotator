"""Class editor — reusable QTableWidget for editing object class ontology."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
import yaml

DEFAULT_POLICIES: list[str] = []


class ClassEditorWidget(QWidget):
    """Editable table of classes. Columns: id, name, graspable."""

    dirty_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dirty = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QHBoxLayout()
        self._add_btn = QPushButton("Add Class")
        self._add_btn.clicked.connect(self._add_row)
        self._delete_btn = QPushButton("Delete Selected")
        self._delete_btn.clicked.connect(self._delete_selected)
        self._load_template_btn = QPushButton("Load Template...")
        self._load_template_btn.clicked.connect(self._load_template)

        toolbar.addWidget(self._add_btn)
        toolbar.addWidget(self._delete_btn)
        toolbar.addWidget(self._load_template_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["ID", "Name", "Graspable"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 50)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(2, 80)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)

        self._table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self._table)

    # ------------------------------------------------------------------
    # Data access
    # ------------------------------------------------------------------

    def to_class_list(self) -> list[dict]:
        result = []
        for row in range(self._table.rowCount()):
            id_item = self._table.item(row, 0)
            name_item = self._table.item(row, 1)
            if id_item is None or name_item is None:
                continue
            name = name_item.text().strip()
            if not name:
                continue
            cb = self._table.cellWidget(row, 2)
            graspable = cb.isChecked() if isinstance(cb, QCheckBox) else True
            result.append({
                "id": int(id_item.text()),
                "name": name,
                "graspable": graspable,
            })
        return result

    def set_class_list(self, classes: list[dict]):
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for cls in sorted(classes, key=lambda c: c.get("id", 0)):
            self._insert_row_internal(
                cls.get("id", 0),
                cls.get("name", ""),
                cls.get("graspable", True),
            )
        self._table.blockSignals(False)
        self._set_dirty(False)

    def load_from_yaml(self, path: str | Path):
        path = Path(path)
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.set_class_list(data.get("classes", []))
        self._set_dirty(False)

    def save_to_yaml(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"classes": self.to_class_list()}
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        self._set_dirty(False)

    @property
    def dirty(self) -> bool:
        return self._dirty

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _insert_row_internal(self, class_id: int, name: str, graspable: bool):
        row = self._table.rowCount()
        self._table.insertRow(row)

        # ID
        id_widget = QTableWidgetItem(str(class_id))
        id_widget.setFlags(id_widget.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, 0, id_widget)

        # Name
        self._table.setItem(row, 1, QTableWidgetItem(name))

        # Graspable checkbox
        cb = QCheckBox()
        cb.setChecked(graspable)
        cb.toggled.connect(lambda: self._set_dirty(True))
        self._table.setCellWidget(row, 2, cb)


    def _add_row(self):
        next_id = 0
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is not None:
                next_id = max(next_id, int(item.text()) + 1)
        self._insert_row_internal(next_id, "", True)
        self._table.selectRow(self._table.rowCount() - 1)
        self._table.editItem(self._table.item(self._table.rowCount() - 1, 1))
        self._set_dirty(True)

    def _delete_selected(self):
        rows = set(idx.row() for idx in self._table.selectedIndexes())
        for row in sorted(rows, reverse=True):
            self._table.removeRow(row)
        if rows:
            self._set_dirty(True)

    def _load_template(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Class Template", "", "YAML Files (*.yaml *.yml);;All Files (*)",
        )
        if path:
            try:
                self.load_from_yaml(path)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to load template:\n{e}")

    def _on_cell_changed(self, row: int, col: int):
        if col == 1:  # name changed
            self._set_dirty(True)

    def _set_dirty(self, dirty: bool):
        self._dirty = dirty
        self.dirty_changed.emit(dirty)


class ClassEditorDialog(QDialog):
    """Dialog wrapper for ClassEditorWidget with OK/Cancel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Classes")
        self.resize(600, 450)

        layout = QVBoxLayout(self)
        self._editor = ClassEditorWidget(self)
        layout.addWidget(self._editor)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def load_from_yaml(self, path: str | Path):
        self._editor.load_from_yaml(path)

    def save_to_yaml(self, path: str | Path):
        self._editor.save_to_yaml(path)

    def to_class_list(self) -> list[dict]:
        return self._editor.to_class_list()

    def set_class_list(self, classes: list[dict]):
        self._editor.set_class_list(classes)

    @property
    def editor(self) -> ClassEditorWidget:
        return self._editor

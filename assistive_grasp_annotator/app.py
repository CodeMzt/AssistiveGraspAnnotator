"""Application class — QApplication wrapper."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from assistive_grasp_annotator.ui.main_window import MainWindow


class Application(QApplication):
    def __init__(self, argv: list[str] = None):
        if argv is None:
            argv = sys.argv
        super().__init__(argv)
        self.setApplicationName("AssistiveGraspAnnotator")
        self.setOrganizationName("AssistiveGrasp")

    def run(self) -> int:
        window = MainWindow()
        window.show()
        return self.exec()

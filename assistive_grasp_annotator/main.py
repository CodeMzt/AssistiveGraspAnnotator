"""Entry point for AssistiveGraspAnnotator."""

from __future__ import annotations

import sys

from assistive_grasp_annotator.app import Application


def main():
    app = Application(sys.argv)
    sys.exit(app.run())


if __name__ == "__main__":
    main()

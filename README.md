# AssistiveGraspAnnotator

Desktop annotation tool for assistive grasping datasets. Supports labeling object bounding boxes and grasp rectangles for a two-stage detection + grasp-prediction pipeline.

## Install

```bash
# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

Requirements:
- Python 3.10+
- PySide6 ≥ 6.5.0
- Pillow, NumPy, PyYAML

## Run

```bash
python -m assistive_grasp_annotator.main
```

## Dataset Structure

```
dataset_root/
  classes.yaml              # Class ontology (required)
  images/
    board_vga/              # Camera subdirectories
      000001.jpg
      000002.jpg
    phone/
      100001.jpg
  annotations/              # Auto-created on save
    000001.json
    000002.json
  splits/                   # Optional: train.txt, val.txt
  generated/                # Exported data (YOLO labels, ROI crops)
```

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+O` | Open dataset directory |
| `Ctrl+S` | Save current annotation |
| `Ctrl+Shift+S` | Save all annotations |
| `A` | BBox mode — click & drag to draw |
| `G` | Grasp mode — 3 clicks (p0, p1, p2) |
| `V` | Select mode — move/resize items |
| `Delete` | Delete selected object or grasp |
| `N / Right` | Next image |
| `P / Left` | Previous image |
| `1` | Set difficulty: easy |
| `2` | Set difficulty: medium |
| `3` | Set difficulty: hard |
| `4` | Set difficulty: invalid |
| `Esc` | Cancel drawing / deselect |
| `Ctrl++` | Zoom in |
| `Ctrl+-` | Zoom out |
| `Ctrl+0` | Zoom to fit |
| `Scroll` | Zoom in/out |
| `Space+drag` | Pan image |

## Annotation Workflow

1. **Open dataset** — `Ctrl+O`, select the dataset root directory
2. **Draw bbox** — Press `A`, click and drag on the image to draw a bounding box
3. **Assign class** — Select the object in the right panel, pick a class from the dropdown
4. **Draw grasp** — Select an object, press `G`, then click 3 points:
   - Click 1: p0 (width axis start)
   - Click 2: p1 (width axis end)
   - Click 3: p2 (depth axis end); p3 is auto-computed
5. **Set difficulty** — Select the grasp, press `1`-`4` or use the dropdown
6. **Save** — `Ctrl+S` (atomic write: temp file → rename)

## Grasp Rectangle Convention

```
p0 → p1 = grasp_width_axis   (gripper open/close direction, cyan arrow)
p1 → p2 = finger_depth_axis  (finger insertion depth, magenta arrow)
p3 = p0 + (p2 - p1)          (auto-computed parallelogram)
```

## Annotation JSON Format

Each image gets one JSON file under `annotations/`:

```json
{
  "image_id": "000001",
  "image_path": "images/board_vga/000001.jpg",
  "width": 640,
  "height": 480,
  "camera": "board_vga",
  "source": "board",
  "split": "train",
  "objects": [
    {
      "instance_id": 1,
      "class_id": 0,
      "class_name": "phone_A",
      "bbox_xyxy": [220, 160, 380, 300],
      "graspable": true,
      "policy": "grasp_rect",
      "grasps": [
        {
          "grasp_id": 1,
          "points": [[245, 220], [355, 220], [355, 245], [245, 245]],
          "axis_convention": "p0_to_p1_is_grasp_width_axis",
          "quality": 1.0,
          "difficulty": "easy",
          "note": ""
        }
      ]
    }
  ]
}
```

## Export

- **Export → Export YOLO Labels**: Generates `class_id cx cy w h` .txt files (normalized) under `generated/detector_yolo/`
- **Export → Export Grasp ROIs**: Crops each graspable object's bbox (+20% padding), transforms grasp points to ROI-local coordinates, saves images + JSON under `generated/grasp_roi/`

## Validation

- **Validate → Validate Current**: Checks bbox bounds, grasp points, difficulty/quality values, graspable constraints
- **Validate → Validate All**: Validates all annotations in the dataset

## Project Structure

```
AssistiveGraspAnnotator/
  requirements.txt
  README.md
  examples/
    classes.yaml
    sample_annotation.json
  assistive_grasp_annotator/
    main.py               # Entry point
    app.py                 # QApplication wrapper
    models/
      classes.py           # ClassInfo, ClassRegistry (from classes.yaml)
      annotation.py        # ObjectAnnotation, GraspAnnotation, AnnotationModel
      dataset.py           # DatasetModel: open dir, scan images, navigate
    ui/
      image_canvas.py      # QGraphicsView: zoom/pan, bbox/grasp drawing, handles
      side_panel.py        # Right panel: object list, class combo, grasp editor
      main_window.py       # MainWindow: menus, 3-panel layout, shortcuts
    tools/
      geometry.py          # Pure geometry functions (no Qt dependency)
      validators.py        # Annotation validation rules
      export_yolo.py       # YOLO label export
      export_grasp_roi.py  # Grasp ROI crop + JSON export
      export_target_maps.py # Stub for future .npz target maps
```

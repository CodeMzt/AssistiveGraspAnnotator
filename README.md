# AssistiveGraspAnnotator

Desktop annotation tool for assistive grasping datasets. Supports labeling object bounding boxes and grasp rectangles, then exporting training data for both the detection model (Model A) and grasp prediction model (Model B).

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Requirements: Python 3.10+, PySide6 ≥ 6.5, Pillow, NumPy, PyYAML.

## Run

```bash
python -m assistive_grasp_annotator.main
```

## Dataset Structure

```
dataset_root/
  classes.yaml              # Class ontology (required for class labels)
  images/
    board_vga/              # Camera subdirectories
      000001.jpg
  annotations/              # Auto-created per-image JSON
    000001.json
  splits/                   # Optional: train.txt, val.txt
  generated/                # Exported training data (created by export)
```

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+N` | New Dataset (from raw image folder) |
| `Ctrl+O` | Open Dataset |
| `Ctrl+S` | Save current annotation |
| `Ctrl+Shift+S` | Save all annotations |
| `A` | BBox mode — click & drag to draw |
| `G` | Grasp mode — first select an object, then 3 clicks (p0→p1→p2) |
| `V` | Select mode — move/resize items |
| `Delete` | Delete selected object or grasp |
| `N / Right` | Next image |
| `P / Left` | Previous image |
| `1 / 2 / 3 / 4` | Set difficulty: easy / medium / hard / invalid |
| `Esc` | Cancel drawing / deselect |
| `Ctrl++/-` | Zoom in/out |
| `Ctrl+0` | Zoom to fit |
| `Scroll` | Zoom in/out |
| `Space+drag` | Pan image |

## Annotation Workflow

1. **Open or create dataset** — `Ctrl+O` (existing) or `Ctrl+N` (new from raw images)
2. **Draw bbox** — Press `A`, click and drag on the image
3. **Assign class** — Select the object in right panel, pick class from dropdown
4. **Draw grasp** — Select an object (click it in V mode), press `G`, then click 3 points:
   - Click 1: **p0** (width axis start)
   - Click 2: **p1** (width axis end) — the axis from p0→p1 defines the gripper closing direction
   - Click 3: **p2** (depth axis end) — p3 is auto-computed as a parallelogram
5. **Set difficulty** — Press `1`-`4` or use dropdown (easy/medium/hard/invalid)
6. **Save** — `Ctrl+S` (atomic write: temp file → rename)

## Grasp Rectangle Convention

```
p0 ──→ p1  =  grasp_width_axis   (gripper open/close direction, cyan arrow)
p1 ──→ p2  =  finger_depth_axis  (finger insertion depth, magenta arrow)
p3 = p0 + (p2 - p1)               (parallelogram, auto-computed)
```

---

## Training Data Pipeline

```
annotations/000001.json          ← Human-edited master annotation
         │
         ├──→  Export → Export YOLO Labels
         │         └──→ generated/detector_yolo/000001.txt     (Model A)
         │
         └──→  Export → Export Target Maps (.npz)
                   └──→ generated/target_maps/000001/
                            obj_001.png                         (ROI image)
                            obj_001.npz   ← q_map, sin2θ, cos2θ, width
                            obj_001.json  ← metadata
```

---

## Model A: Detection (YOLO format)

Each image gets one `.txt` file with one line per annotated object:

```
class_id cx_norm cy_norm w_norm h_norm
```

| Field | Description | Range |
|-------|-------------|-------|
| `class_id` | Integer class index from classes.yaml | 0..N-1 |
| `cx_norm` | Bbox center x / image width | [0, 1] |
| `cy_norm` | Bbox center y / image height | [0, 1] |
| `w_norm` | Bbox width / image width | [0, 1] |
| `h_norm` | Bbox height / image height | [0, 1] |

**Export**: `Export → Export YOLO Labels`  
**Output**: `generated/detector_yolo/{camera}/{image_id}.txt`  
**Compatible with**: YOLOv5/v8/v11, Ultralytics, any normalized-bbox detector.

---

## Model B: Grasp Prediction (Target Maps)

Each graspable object produces one `.npz` file containing pixel-level supervision maps.

Format follows GG-CNN (Morrison et al., RSS 2018): square maps, compact-polygon (centre-1/3) encoding, sin(2θ)/cos(2θ) angle wrapping.

### .npz Keys

| Key | Shape | dtype | Range | Description |
|-----|-------|-------|-------|-------------|
| `q_map` | (S, S) | float32 | [0, 1] | Per-pixel grasp quality |
| `sin2theta_map` | (S, S) | float32 | [-1, 1] | sin(2θ) orientation encoding |
| `cos2theta_map` | (S, S) | float32 | [-1, 1] | cos(2θ) orientation encoding |
| `width_map` | (S, S) | float32 | [0, 1] | Grasp width, normalised by map_size |

### Map dimensions

Default `300 × 300` (square, matches GG-CNN). Configurable via `map_size` parameter.

### ROI letterbox

The ROI crop (bbox + 20% padding) is resized with **preserved aspect ratio** and centred on a black canvas — no stretching distortion.

### Compact polygon encoding (GG-CNN convention)

Only the **centre third** of each grasp rectangle is set as positive in Q_map (binary fill). This teaches the network to predict grasp *centres*, not arbitrary points inside the rectangle.

### Quality mapping

| Difficulty | Quality |
|-----------|---------|
| easy | 1.0 |
| medium | 0.7 |
| hard | 0.4 |
| invalid | 0.0 (excluded from maps) |

### Overlap handling

When multiple grasps overlap on the same pixel, the one with the **highest quality** takes precedence for all map channels.

### Orientation encoding

θ = atan2(p1.y − p0.y, p1.x − p0.x). Encoded as sin(2θ) and cos(2θ) to avoid the wrap-around discontinuity at ±π/2 (antipodal grasps are equivalent).

### Training usage

```python
import numpy as np
data = np.load("obj_001.npz")
q_map   = data["q_map"]          # (240, 320) float32
sin2t   = data["sin2theta_map"]  # (240, 320) float32
cos2t   = data["cos2theta_map"]  # (240, 320) float32
width   = data["width_map"]      # (240, 320) float32

# Recover angle:  θ = 0.5 * atan2(sin2t, cos2t)
# Recover quality at each pixel: q_map[pixel]
```

**Export**: `Export → Export Target Maps (.npz)`  
**Output**: `generated/target_maps/{image_id}/obj_{instance_id:03d}.{png,npz,json}`

### Companion ROI JSON

Each .npz is accompanied by a `obj_{id}.json` with metadata:

```json
{
  "source_image": "images/board_vga/000001.jpg",
  "source_bbox": [220, 160, 380, 300],
  "padded_bbox": [204, 144, 396, 316],
  "map_size": [320, 240],
  "instance_id": 1,
  "class_id": 0,
  "class_name": "phone_A",
  "grasps": [
    {
      "grasp_id": 1,
      "points_roi": [[41.0, 76.0], [151.0, 76.0], [151.0, 101.0], [41.0, 101.0]],
      "quality": 1.0,
      "difficulty": "easy"
    }
  ]
}
```

---

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

---

## Validation

- **Validate → Validate Current**: checks bbox bounds, grasp points, difficulty/quality values
- **Validate → Validate All**: validates all annotations in the dataset

---

## Project Structure

```
AssistiveGraspAnnotator/
  requirements.txt
  README.md
  examples/
    classes.yaml
    sample_annotation.json
  assistive_grasp_annotator/
    main.py                  # Entry point
    app.py                   # QApplication wrapper
    models/
      classes.py             # ClassInfo, ClassRegistry
      annotation.py          # ObjectAnnotation, GraspAnnotation, AnnotationModel
      dataset.py             # DatasetModel: open/create, scan, navigate
    ui/
      image_canvas.py        # QGraphicsView: zoom/pan, bbox/grasp drawing, handles
      side_panel.py          # Right panel: object/grasp lists, editors
      main_window.py         # MainWindow: menus, layout, shortcuts, signal wiring
      class_editor.py        # Class editor table + dialog
      dataset_wizard.py      # New Dataset wizard dialog
    tools/
      geometry.py            # Pure geometry functions
      validators.py          # Annotation validation rules
      export_yolo.py         # Model A: YOLO label export
      export_grasp_roi.py    # Grasp ROI crop + JSON export
      export_target_maps.py  # Model B: .npz target map export
```

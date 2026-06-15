# AssistiveGraspAnnotator

Desktop and web annotation tool for assistive grasping datasets. The current system contract is Model A V2 / EthosSafeDetV2: scene-level OV5640 VGA annotations provide class, bbox, and optional orientation labels for a single detection/localization/orientation model. The historical Model B/ROI grasp-rectangle export path is deprecated reference tooling only.

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

## Run Web Collaboration Server

The browser UI is built once by Vite, then served by the same Python/FastAPI
process as the API. No separate frontend server is needed in deployment.

```bash
pip install -r requirements-dev.txt
cd web_frontend
npm install
npm run build
cd ..
```

Start the local service with the one-click Windows launcher:

```bat
start_web.bat
```

The launcher creates and uses the project-local `.venv` automatically, then
installs only the Web runtime dependencies from `requirements-web.txt` into that
virtual environment. It does not install packages into the system Python.

By default the managed dataset library is fixed at
`D:\AssistiveGraspAnnotatorData\datasets`. The Web UI manages datasets by
dataset name; paths stay internal to the server.

Or start the same service from PowerShell:

```bash
.\scripts\start_web.ps1
```

Then open `http://<server-ip>:8000/` from the intranet. Users enter a
username, select or create a named dataset, upload images, acquire an image
lock, annotate, save, validate, and export.

Large browser uploads use chunked transfer so they can pass through small
reverse-proxy body limits. The frontend sends about 960 KiB per chunk, prequeues
parallel requests, and shows confirmed chunk count plus aggregate throughput.
If a public nginx sits in front of FRP, disable request buffering so nginx
streams each chunk to FRP while the browser is still sending it; otherwise the
browser can show a chunk as uploaded while nginx is still forwarding it upstream.

```nginx
server {
    client_max_body_size 200m;

    location / {
        proxy_pass http://127.0.0.1:18080;
        proxy_http_version 1.1;
        proxy_request_buffering off;
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

The browser may still physically upload only about six concurrent requests over
plain HTTP/1.1. The Web UI defaults to `Turbo x18` so extra chunks are already
queued when a connection frees up. For true higher-than-six concurrency from
the browser, terminate HTTPS on nginx and enable HTTP/2.

Web save behavior intentionally matches the desktop tool: saving writes the
annotation JSON as an intermediate state after lock/ETag/basic-shape checks.
Validation warnings and errors are reported through `Validate` but do not block
save.

Key environment variables:

| Variable | Purpose |
|----------|---------|
| `AGA_DATASET_ROOTS` | Semicolon-separated whitelist of server/share roots allowed for opening datasets |
| `AGA_UPLOAD_ROOT` | Managed directory where browser-created datasets are stored |
| `AGA_STATE_DB` | SQLite file for Web-only state: registered datasets, locks, jobs, audit rows |
| `AGA_LOCK_TTL_SECONDS` | Edit lock timeout in seconds, default `900` |
| `AGA_PORT` | Server port, default `8000` |

Recommended repair/regression checks:

```bash
python -m unittest tests.test_web_backend
cd web_frontend
npm test
npm run build
cd ..
python -m compileall assistive_grasp_annotator tests
```

For real acceptance, start `python -m assistive_grasp_annotator.web.server`,
open the page, log in, open a whitelisted dataset, acquire an image lock, draw a
bbox and a two-point main axis when required, edit difficulty/note, save, refresh, and verify the
saved `annotations/{camera}/{image}.json` plus the V2 exports under
`generated/`.

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
| `C` / `A` | BBox mode — click & drag to draw |
| `E` | Axis mode — first select an object, then 2 clicks for `main_axis_points` |
| `Q` / `V` | Select mode — move/resize items |
| `Delete` | Delete selected object or annotation handle |
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
4. **Draw main axis when needed** — For graspable preset classes with a stable direction, mark `yaw_label_status=valid` and add the two-point main axis. Directionless, ambiguous, or occluded objects must keep an explicit non-valid yaw status.
5. **Set difficulty** — Press `1`-`4` or use dropdown (easy/medium/hard/invalid)
6. **Save** — `Ctrl+S` (atomic write: temp file → rename)

## Model A V2 Orientation Convention

Orientation is an image-plane object/main-axis angle in the original VGA coordinate system. Exporters encode it as `sin(2theta)` and `cos(2theta)` so antipodal directions share one representation. Orientation is valid only when `yaw_label_status == "valid"` and `main_axis_points` exist; otherwise `theta_valid`/`angle_mask` must be false.

---

## Training Data Pipeline

```
annotations/000001.json          ← Human-edited master annotation
         │
         ├──→  Export → Export YOLO-Angle Labels
         │         └──→ generated/detector_yolo_angle/000001.txt
         │
         └──→  Deprecated reference only: Export Target Maps (.npz)
                   └──→ generated/target_maps/000001/
                            obj_001.png                         (legacy ROI image)
                            obj_001.npz   ← q_map, sin2θ, cos2θ, width
                            obj_001.json  ← metadata
```

---

## Model A V2: Detection + Orientation

Each image gets one `.txt` file with one line per annotated object:

```
class_id cx_norm cy_norm w_norm h_norm sin2theta cos2theta yaw_valid angle_mask
```

| Field | Description | Range |
|-------|-------------|-------|
| `class_id` | Integer class index from classes.yaml | 0..N-1 |
| `cx_norm` | Bbox center x / image width | [0, 1] |
| `cy_norm` | Bbox center y / image height | [0, 1] |
| `w_norm` | Bbox width / image width | [0, 1] |
| `h_norm` | Bbox height / image height | [0, 1] |
| `sin2theta` | `sin(2theta)` from VGA main-axis annotation | [-1, 1] |
| `cos2theta` | `cos(2theta)` from VGA main-axis annotation | [-1, 1] |
| `yaw_valid` | 1 only when `yaw_label_status == "valid"` | 0 or 1 |
| `angle_mask` | 1 only when the sample participates in orientation loss | 0 or 1 |

**Export**: `Export → Export YOLO-Angle Labels`
**Output**: `generated/detector_yolo_angle/{camera}/{image_id}.txt`
**Compatible with**: detector training code that consumes bbox plus `sin(2theta), cos(2theta)` orientation targets.

---

## Deprecated Reference: Target Maps

The old per-object target-map/ROI export is retained only for reference and migration. It is not part of the current Model A V2 firmware contract and must not be used to justify a separate Model B deployment path.

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
q_map   = data["q_map"]          # (300, 300) float32
sin2t   = data["sin2theta_map"]  # (300, 300) float32
cos2t   = data["cos2theta_map"]  # (300, 300) float32
width   = data["width_map"]      # (300, 300) float32

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
  "map_size": 300,
  "letterbox_offset": [22, 22],
  "scale": 1.071428,
  "instance_id": 1,
  "class_id": 0,
  "class_name": "phone",
  "grasps": [
    {
      "grasp_id": 1,
      "points_map": [[70.7, 81.4], [155.4, 81.4], [155.4, 107.1], [70.7, 107.1]],
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
      "class_name": "phone",
      "yaw_label_status": "valid",
      "main_axis_points": [[245, 220], [355, 220]],
      "bbox_xyxy": [220, 160, 380, 300],
      "graspable": true,
      "policy": "grasp_rect",
      "occlusion_level": 0,
      "difficulty": "easy",
      "note": ""
    }
  ]
}
```

---

## Validation

- **Validate → Validate Current**: checks bbox bounds, yaw status/main-axis consistency, occlusion, difficulty, and class-specific yaw requirements
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
      image_canvas.py        # QGraphicsView: zoom/pan, bbox/main-axis drawing, handles
      side_panel.py          # Right panel: object/grasp lists, editors
      main_window.py         # MainWindow: menus, layout, shortcuts, signal wiring
      class_editor.py        # Class editor table + dialog
      dataset_wizard.py      # New Dataset wizard dialog
    tools/
      geometry.py            # Pure geometry functions
      validators.py          # Annotation validation rules
      export_yolo.py         # Legacy normalized bbox export
      export_yolo_angle.py   # Model A V2: bbox + sin2theta/cos2theta export
      export_grasp_roi.py    # Grasp ROI crop + JSON export
      export_target_maps.py  # Deprecated reference: .npz target map export
```

## 2026-06-14 object_vocab_v1 alignment

New datasets should use `examples/object_vocab_v1.json` and `examples/classes.yaml` with canonical target IDs `0 earbud`, `1 phial`, `2 bottle`, `3 phone`, `4 remote`, `5 tissue`, `6 apple`. Historical migration tools may still mention legacy cup aliases, but new annotations must not assign cup/small_cup_A/CUP as target classes.


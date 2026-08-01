# AssistiveGraspAnnotator

Desktop and web annotation tool for assistive grasping datasets. The current firmware-facing contract is Model A V2 / EthosSafeDetV2 for scene-level class, bbox, and optional orientation labels. The active contour-refinement path uses SAM/SAM2 sidecars and the new parallel `assistive_grasp_contour_model` / ROIContourNet training repo. This tool stores and reviews masks/smooth contours only; old ROI grasp-rectangle target maps are not an active export or training contract.

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
| `M` | Mask Review mode for the selected object |
| `G` | Generate or refresh the selected object's mask candidate |
| `O` | Toggle mask/contour overlay |
| `0`-`5` | Score the selected mask candidate |
| `[` / `]` | Previous / next object in the current image |
| `R` | Clear the selected object's mask review |
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
5. **Review mask/contour candidates when needed** — Press `M`, select an object, press `G`, inspect the translucent mask plus smooth closed contour, then score with `0`-`5`. Scores and failure tags are stored in `generated/mask_reviews/`; they do not change the master bbox/yaw annotation JSON.
6. **Set difficulty** — Use the right panel dropdown (easy/medium/hard)
7. **Save** — `Ctrl+S` (atomic write: temp file → rename)

## SAM Mask Teacher

Mask/contour candidates are generated by the isolated SAM teacher path. The web backend only accepts candidate metadata whose algorithm_version starts with sam2_; unsupported historical candidates are ignored instead of being shown as latest masks.

Prepare the teacher environment on ma2 with:

`powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_sam_teacher.ps1
`

The web API calls .venv_sam\Scripts\python.exe by default, or AGA_SAM_PYTHON when set. If the SAM environment is missing, POST /mask-candidate returns 503 and no fallback mask is generated.

## Model A V2 Orientation Convention

Orientation is an image-plane object/main-axis angle in the original VGA coordinate system. Exporters encode it as `sin(2theta)` and `cos(2theta)` so antipodal directions share one representation. Orientation is valid only when `yaw_label_status == "valid"` and `main_axis_points` exist; otherwise `theta_valid`/`angle_mask` must be false.

---

## Training Data Pipeline

```
annotations/000001.json
  |-- Export YOLO-Angle Labels -> generated/detector_yolo_angle/{camera}/000001.txt
  |-- SAM mask sidecars        -> generated/mask_candidates/{camera}/{image}/obj_001/*.mask.png
  |-- Mask review sidecars     -> generated/mask_reviews/{camera}/{image}/obj_001/review.json
  `-- ROIContourNet training   -> sam_mask_manifest_v1.jsonl -> roi_samples/{images,masks,records.jsonl}
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

## ROI Mask / Smooth Contour Review

Mask review is a PC/ma2-side refinement pipeline. It is not a firmware ABI and does not introduce retired grasp-width fields.

Each selected object can generate a candidate containing:

| Field | Description |
|-------|-------------|
| `mask.png` | Full-image binary mask candidate; this is the authoritative segmentation artifact |
| `preview.png` | Transparent overlay used by the browser canvas |
| `smooth_contour_px` | Dense closed contour derived from the mask for review and geometry analysis |
| `anchor_px` | Candidate mask centroid / localization anchor |
| `quality_auto_score` | Teacher heuristic score used only for queue ordering and review context |

Manual review uses 0-3 scoring when review is needed:

| Score | Meaning |
|-------|---------|
| `3` | Excellent; directly usable for training |
| `2` | Usable with minor boundary defects |
| `1` | Borderline; keep for targeted review only |
| `0` | Reject |

The mask is the training authority. The smooth contour is a dense derivative for visualization, anchor estimation, and later risk-map analysis; do not replace it with a low-vertex polygon as the primary label.

---

## ROIContourNet Training Export

The old target-map export has been retired from the active workflow. Contour training data is produced from SAM sidecars by the parallel `assistive_grasp_contour_model` repo:

```powershell
build_sam_mask_manifest D:\AssistiveGraspAnnotatorData\datasets\new_dataset --out runs\new_dataset\sam_mask_manifest_v1.jsonl --summary-json runs\new_dataset\sam_mask_manifest_summary.json
export_roi_contour_samples runs\new_dataset\sam_mask_manifest_v1.jsonl --out runs\new_dataset\roi_samples --status accept
```

The export contains RGB ROI images, binary ROI masks, source bbox/crop metadata, SAM provenance, and automatic QA status. It does not contain grasp width, grasp yaw, grasp rectangles, Q maps, or target-map channels.

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
      generate_mask_candidates.py # SAM/SAM2 mask sidecar generation
      mask_common.py              # Mask, smooth-contour, and sidecar helpers
```

## 2026-06-14 object_vocab_v1 alignment

New datasets should use `examples/object_vocab_v1.json` and `examples/classes.yaml` with canonical target IDs `0 earbud`, `1 phial`, `2 bottle`, `3 phone`, `4 remote`, `5 tissue`, `6 apple`. Historical migration tools may still read old labels for one-way migration, but active classes and examples must use the canonical seven names only.


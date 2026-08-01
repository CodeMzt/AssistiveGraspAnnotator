"""SAM 2 mask teacher runner.

Run this module inside the isolated .venv_sam environment. The main web service
calls it as a subprocess so PyTorch/SAM dependencies do not pollute the web venv.
"""

from __future__ import annotations

import argparse
import json
import os
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from assistive_grasp_annotator.tools.mask_common import (
    DEFAULT_SAM_ALGORITHM_VERSION,
    atomic_write_json,
    build_mask_candidate_payload,
    clamp_bbox,
)


class SamRunnerError(RuntimeError):
    pass


class Sam2Runtime:
    def __init__(self) -> None:
        self.torch = _import_torch()
        self.device = os.environ.get("AGA_SAM_DEVICE") or ("cuda" if self.torch.cuda.is_available() else "cpu")
        self.model_id = os.environ.get("AGA_SAM2_MODEL_ID", "facebook/sam2.1-hiera-small")
        self.predictor = self._load_predictor()

    def predict_mask(self, image: Image.Image, bbox: list[int]) -> tuple[np.ndarray, dict[str, Any]]:
        image_np = np.asarray(image.convert("RGB"))
        self.predictor.set_image(image_np)
        point_coords, point_labels = _prompt_points(bbox, image_np.shape[1], image_np.shape[0])
        box = np.array(bbox, dtype=np.float32)
        context = self.torch.inference_mode()
        autocast = self.torch.autocast(self.device, dtype=self.torch.bfloat16) if self.device == "cuda" else nullcontext()
        with context, autocast:
            masks, scores, _ = self.predictor.predict(
                point_coords=point_coords,
                point_labels=point_labels,
                box=box,
                multimask_output=True,
            )
        mask, score = _select_mask(np.asarray(masks), np.asarray(scores), bbox)
        mask = _restrict_to_prompt_roi(mask, bbox, image_np.shape[1], image_np.shape[0])
        meta = {
            "sam_model_id": self.model_id,
            "sam_device": self.device,
            "sam_score": round(float(score), 6),
            "prompt_mode": "bbox_center_positive_outer_negative",
        }
        return mask, meta

    def _load_predictor(self):
        try:
            from sam2.sam2_image_predictor import SAM2ImagePredictor
        except Exception as exc:
            raise SamRunnerError(
                "Python package sam2 is not installed in the SAM teacher environment. "
                "Run scripts/setup_sam_teacher.ps1."
            ) from exc

        checkpoint = os.environ.get("AGA_SAM2_CHECKPOINT")
        config = os.environ.get("AGA_SAM2_CONFIG")
        if checkpoint or config:
            if not checkpoint or not config:
                raise SamRunnerError("Set both AGA_SAM2_CHECKPOINT and AGA_SAM2_CONFIG for local SAM2 checkpoints.")
            from sam2.build_sam import build_sam2

            model = build_sam2(config, checkpoint, device=self.device)
            return SAM2ImagePredictor(model)

        if not hasattr(SAM2ImagePredictor, "from_pretrained"):
            raise SamRunnerError(
                "Installed sam2 does not support from_pretrained. Set AGA_SAM2_CHECKPOINT and AGA_SAM2_CONFIG."
            )
        try:
            return SAM2ImagePredictor.from_pretrained(self.model_id, device=self.device)
        except TypeError:
            predictor = SAM2ImagePredictor.from_pretrained(self.model_id)
            if hasattr(predictor, "model"):
                predictor.model.to(self.device)
            return predictor


def generate_one(runtime: Sam2Runtime, job: dict[str, Any]) -> dict[str, Any]:
    image_path = Path(job["image_path"])
    artifact_dir = Path(job["artifact_dir"])
    annotation = dict(job["annotation"])
    obj = dict(job["obj"])
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    bbox = clamp_bbox(obj.get("bbox_xyxy", [0, 0, width, height]), width, height)
    mask, meta = runtime.predict_mask(image, bbox)
    candidate = build_mask_candidate_payload(
        image_path=image_path,
        annotation=annotation,
        obj=obj,
        artifact_dir=artifact_dir,
        full_mask=mask,
        algorithm_version=os.environ.get("AGA_SAM_ALGORITHM_VERSION", DEFAULT_SAM_ALGORITHM_VERSION),
        source="sam2_teacher",
        extra=meta,
    )
    atomic_write_json(artifact_dir / f"{candidate['candidate_id']}.json", candidate)
    return candidate


def run_batch(request_path: Path) -> dict[str, Any]:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    jobs = list(request.get("jobs") or [])
    runtime = Sam2Runtime()
    results: list[dict[str, Any]] = []
    for job in jobs:
        try:
            results.append({"ok": True, "candidate": generate_one(runtime, job)})
        except Exception as exc:
            results.append({
                "ok": False,
                "image_path": job.get("image_path"),
                "instance_id": (job.get("obj") or {}).get("instance_id"),
                "error": str(exc),
            })
    return {"schema_version": "sam_teacher_batch_v1", "results": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-request-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    payload = run_batch(args.batch_request_json)
    atomic_write_json(args.output_json, payload)


def _import_torch():
    try:
        import torch
    except Exception as exc:
        raise SamRunnerError(
            "PyTorch is not installed in the SAM teacher environment. Run scripts/setup_sam_teacher.ps1."
        ) from exc
    return torch


def _prompt_points(bbox: list[int], width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    x1, y1, x2, y2 = bbox
    bw = max(1, x2 - x1)
    bh = max(1, y2 - y1)
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    margin = max(4.0, max(bw, bh) * 0.10)
    points: list[list[float]] = [[cx, cy]]
    labels: list[int] = [1]
    candidates = [
        [cx, y1 - margin],
        [cx, y2 + margin],
        [x1 - margin, cy],
        [x2 + margin, cy],
    ]
    for px, py in candidates:
        if 0 <= px < width and 0 <= py < height:
            points.append([float(px), float(py)])
            labels.append(0)
    return np.array(points, dtype=np.float32), np.array(labels, dtype=np.int32)


def _select_mask(masks: np.ndarray, scores: np.ndarray, bbox: list[int]) -> tuple[np.ndarray, float]:
    arr = np.asarray(masks)
    if arr.ndim == 2:
        arr = arr[None, :, :]
    score_arr = np.asarray(scores).reshape(-1)
    if score_arr.size < arr.shape[0]:
        score_arr = np.pad(score_arr, (0, arr.shape[0] - score_arr.size), constant_values=0.0)
    x1, y1, x2, y2 = bbox
    bbox_area = max(1, (x2 - x1) * (y2 - y1))
    best_index = 0
    best_score = -1e9
    for index in range(arr.shape[0]):
        mask = arr[index] > 0
        area = int(mask.sum())
        inside = int(mask[y1:y2, x1:x2].sum())
        fill = area / float(bbox_area)
        inside_ratio = inside / float(max(1, area))
        fill_penalty = abs(np.log(max(fill, 1e-6))) * 0.10
        candidate_score = float(score_arr[index]) + inside_ratio * 0.30 - fill_penalty
        if fill < 0.03 or fill > 1.60:
            candidate_score -= 0.50
        if candidate_score > best_score:
            best_score = candidate_score
            best_index = index
    return (arr[best_index] > 0), float(score_arr[best_index])


def _restrict_to_prompt_roi(mask: np.ndarray, bbox: list[int], width: int, height: int) -> np.ndarray:
    x1, y1, x2, y2 = bbox
    pad = max(4, int(round(max(x2 - x1, y2 - y1) * 0.12)))
    rx1 = max(0, x1 - pad)
    ry1 = max(0, y1 - pad)
    rx2 = min(width, x2 + pad)
    ry2 = min(height, y2 + pad)
    allowed = np.zeros((height, width), dtype=bool)
    allowed[ry1:ry2, rx1:rx2] = True
    return mask.astype(bool) & allowed


if __name__ == "__main__":
    main()
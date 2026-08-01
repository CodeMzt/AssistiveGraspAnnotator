"""Main-environment client for the isolated SAM teacher runner."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from assistive_grasp_annotator.tools.mask_common import (
    atomic_write_json,
    build_mask_candidate_payload,
    clamp_bbox,
)


class SamTeacherError(RuntimeError):
    pass


def generate_sam_mask_candidate(
    image_path: Path,
    annotation: dict[str, Any],
    obj: dict[str, Any],
    artifact_dir: Path,
) -> dict[str, Any]:
    if _fake_mode_enabled():
        return _generate_fake_candidate(image_path, annotation, obj, artifact_dir)
    results = generate_sam_mask_candidates_batch([
        {
            "image_path": str(image_path),
            "annotation": annotation,
            "obj": obj,
            "artifact_dir": str(artifact_dir),
        }
    ])
    first = results[0] if results else {"ok": False, "error": "SAM runner returned no result."}
    if not first.get("ok"):
        raise SamTeacherError(str(first.get("error") or "SAM runner failed."))
    return first["candidate"]


def generate_sam_mask_candidates_batch(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not jobs:
        return []
    if _fake_mode_enabled():
        results: list[dict[str, Any]] = []
        for job in jobs:
            try:
                candidate = _generate_fake_candidate(
                    Path(job["image_path"]),
                    job["annotation"],
                    job["obj"],
                    Path(job["artifact_dir"]),
                )
                results.append({"ok": True, "candidate": candidate})
            except Exception as exc:  # pragma: no cover - fake failure diagnostics
                results.append({"ok": False, "error": str(exc)})
        return results

    python_exe = _sam_python()
    repo_root = Path(__file__).resolve().parents[2]
    timeout_s = int(os.environ.get("AGA_SAM_TIMEOUT_SECONDS", "600"))
    with tempfile.TemporaryDirectory(prefix="aga_sam_") as tmp:
        request_path = Path(tmp) / "request.json"
        output_path = Path(tmp) / "output.json"
        request_path.write_text(json.dumps({"jobs": jobs}, ensure_ascii=False), encoding="utf-8")
        env = os.environ.copy()
        existing_path = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(repo_root) if not existing_path else f"{repo_root}{os.pathsep}{existing_path}"
        command = [
            str(python_exe),
            "-m",
            "assistive_grasp_annotator.tools.sam_teacher",
            "--batch-request-json",
            str(request_path),
            "--output-json",
            str(output_path),
        ]
        completed = subprocess.run(
            command,
            cwd=str(repo_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if completed.returncode != 0:
            raise SamTeacherError(_format_runner_error(completed))
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SamTeacherError(f"SAM runner did not write a valid output JSON: {exc}") from exc
        return list(payload.get("results") or [])


def _sam_python() -> Path:
    configured = os.environ.get("AGA_SAM_PYTHON")
    if configured:
        path = Path(configured)
    else:
        path = Path(__file__).resolve().parents[2] / ".venv_sam" / "Scripts" / "python.exe"
    if not path.exists():
        raise SamTeacherError(
            "SAM teacher environment is not ready. Run scripts/setup_sam_teacher.ps1 or set AGA_SAM_PYTHON."
        )
    return path


def _fake_mode_enabled() -> bool:
    return os.environ.get("AGA_MASK_TEACHER_MODE") == "fake"


def _generate_fake_candidate(
    image_path: Path,
    annotation: dict[str, Any],
    obj: dict[str, Any],
    artifact_dir: Path,
) -> dict[str, Any]:
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    x1, y1, x2, y2 = clamp_bbox(obj.get("bbox_xyxy", [0, 0, width, height]), width, height)
    yy, xx = np.mgrid[0:height, 0:width]
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    rx = max(1.0, (x2 - x1) * 0.46)
    ry = max(1.0, (y2 - y1) * 0.46)
    mask = (((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2) <= 1.0
    candidate = build_mask_candidate_payload(
        image_path=image_path,
        annotation=annotation,
        obj=obj,
        artifact_dir=artifact_dir,
        full_mask=mask,
        algorithm_version="sam2_fake_test_v1",
        source="test_fake_sam_teacher",
        extra={"sam_model_id": "fake", "sam_device": "cpu", "prompt_mode": "bbox_center_test"},
    )
    atomic_write_json(artifact_dir / f"{candidate['candidate_id']}.json", candidate)
    return candidate


def _format_runner_error(completed: subprocess.CompletedProcess[str]) -> str:
    stderr = (completed.stderr or "").strip()
    stdout = (completed.stdout or "").strip()
    details = stderr or stdout or f"exit code {completed.returncode}"
    if len(details) > 4000:
        details = details[-4000:]
    return f"SAM runner failed: {details}"
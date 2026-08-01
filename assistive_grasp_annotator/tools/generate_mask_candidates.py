"""Batch-generate SAM ROI mask candidates for a dataset.

This is a PC/ma2-side teacher precompute step. It writes sidecar artifacts under
generated/mask_candidates and does not modify master annotation JSON.
"""

from __future__ import annotations

import argparse
import json
import time
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Iterable

from assistive_grasp_annotator.tools.mask_common import object_signature
from assistive_grasp_annotator.tools.sam_teacher_client import SamTeacherError, generate_sam_mask_candidates_batch
from assistive_grasp_annotator.web.datasets import WebDataset
from assistive_grasp_annotator.web.ids import encode_image_id


def generate_dataset_masks(
    dataset_root: Path,
    *,
    force: bool = False,
    limit: int | None = None,
    progress_every: int = 50,
    batch_size: int = 32,
    image_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    dataset = WebDataset(dataset_root)
    started = time.time()
    stats: dict[str, Any] = {
        "dataset_root": str(dataset.root),
        "force": force,
        "batch_size": batch_size,
        "image_count": 0,
        "object_count": 0,
        "queued": 0,
        "generated": 0,
        "skipped_current": 0,
        "failed": 0,
        "failures": [],
        "elapsed_s": 0.0,
    }
    pending: list[dict[str, Any]] = []

    def flush_pending() -> None:
        if not pending:
            return
        try:
            results = generate_sam_mask_candidates_batch(pending)
        except SamTeacherError as exc:
            for job in pending:
                _record_failure(stats, job, str(exc))
            pending.clear()
            return
        for job, result in zip(pending, results):
            if result.get("ok"):
                stats["generated"] += 1
            else:
                _record_failure(stats, job, str(result.get("error") or "unknown SAM failure"))
        if len(results) < len(pending):
            for job in pending[len(results):]:
                _record_failure(stats, job, "SAM runner returned too few results")
        pending.clear()
        done = stats["generated"] + stats["skipped_current"] + stats["failed"]
        if progress_every > 0 and done % progress_every == 0:
            print(json.dumps({**stats, "elapsed_s": round(time.time() - started, 3)}, ensure_ascii=False), flush=True)

    max_jobs = limit if limit is not None else None
    entries = dataset.list_images("annotated") if image_keys is None else _entries_for_image_keys(dataset, image_keys)
    for entry in entries:
        stats["image_count"] += 1
        annotation = dataset.annotation_payload(entry.image_id)["annotation"]
        for obj in annotation.get("objects", []):
            instance_id = int(obj.get("instance_id") or 0)
            if instance_id <= 0:
                continue
            stats["object_count"] += 1
            if max_jobs is not None and stats["queued"] >= max_jobs:
                flush_pending()
                stats["elapsed_s"] = round(time.time() - started, 3)
                return stats
            if not force and _has_current_candidate(dataset, entry.image_id, instance_id, annotation, obj):
                stats["skipped_current"] += 1
                continue
            pending.append({
                "image_key": entry.image_key,
                "image_id": entry.image_id,
                "image_path": str(dataset.image_path_for_id(entry.image_id)),
                "annotation": annotation,
                "obj": obj,
                "artifact_dir": str(dataset._mask_artifact_root(entry.image_id, instance_id, "mask_candidates")),
            })
            stats["queued"] += 1
            if len(pending) >= max(1, batch_size):
                flush_pending()

    flush_pending()
    stats["elapsed_s"] = round(time.time() - started, 3)
    return stats


def _entries_for_image_keys(dataset: WebDataset, image_keys: Iterable[str]) -> Iterable[SimpleNamespace]:
    """Use an immutable external image contract rather than Web UI status.

    This is required when a formal downstream snapshot includes valid annotation
    files that are not currently marked ``annotated`` in the WebDataset index.
    The master annotations remain read-only; only SAM sidecars are generated.
    """
    seen: set[str] = set()
    known = {str(key).replace("\\", "/"): (str(key), path) for key, path in dataset._image_by_key.items()}
    for raw_key in image_keys:
        contract_key = str(raw_key).strip().replace("\\", "/")
        if not contract_key or contract_key in seen:
            continue
        seen.add(contract_key)
        candidates = [key for key in known if Path(key).with_suffix("").as_posix() == contract_key]
        if len(candidates) != 1:
            raise FileNotFoundError(f"Contract image key must resolve exactly once: {contract_key} -> {candidates}")
        normalized_key = candidates[0]
        image_key, image_path = known[normalized_key]
        annotation_path = dataset._get_annotation_path(image_path)
        if not annotation_path.is_file():
            raise FileNotFoundError(f"Contract annotation does not exist: {contract_key} -> {annotation_path}")
        yield SimpleNamespace(image_id=encode_image_id(image_key), image_key=image_key)


def _record_failure(stats: dict[str, Any], job: dict[str, Any], error: str) -> None:
    stats["failed"] += 1
    if len(stats["failures"]) < 200:
        obj = job.get("obj") or {}
        stats["failures"].append({
            "image_key": job.get("image_key") or job.get("image_path"),
            "instance_id": int(obj.get("instance_id") or 0),
            "error": error,
        })


def _has_current_candidate(
    dataset: WebDataset,
    image_id: str,
    instance_id: int,
    annotation: dict[str, Any],
    obj: dict[str, Any],
) -> bool:
    path = dataset._latest_candidate_path(image_id, instance_id)
    if path is None:
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return data.get("annotation_signature") == object_signature(annotation, obj)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--progress-every", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--image-key-file", type=Path, default=None, help="Optional exact camera/image key list (without extension); bypasses WebDataset annotated-state filtering.")
    args = parser.parse_args()
    stats = generate_dataset_masks(
        args.dataset_root,
        force=args.force,
        limit=args.limit,
        progress_every=args.progress_every,
        batch_size=args.batch_size,
        image_keys=args.image_key_file.read_text(encoding="utf-8").splitlines() if args.image_key_file else None,
    )
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

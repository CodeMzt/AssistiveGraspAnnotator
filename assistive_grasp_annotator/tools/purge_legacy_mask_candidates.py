"""Purge retired RGB/HSV mask teacher sidecar artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from assistive_grasp_annotator.tools.mask_common import atomic_write_json, is_supported_mask_candidate


def purge_legacy_mask_candidates(dataset_root: Path, *, apply: bool = False) -> dict[str, Any]:
    dataset_root = dataset_root.resolve()
    candidate_root = dataset_root / "generated" / "mask_candidates"
    review_root = dataset_root / "generated" / "mask_reviews"
    report: dict[str, Any] = {
        "schema_version": "legacy_mask_candidate_purge_v1",
        "dataset_root": str(dataset_root),
        "applied": apply,
        "purge_rule": "delete candidates whose algorithm_version is not accepted by is_supported_mask_candidate",
        "candidate_json_deleted": 0,
        "artifact_png_deleted": 0,
        "review_json_deleted": 0,
        "empty_dirs_removed": 0,
        "legacy_candidate_ids": [],
        "errors": [],
    }
    legacy_candidate_ids: set[str] = set()
    if candidate_root.exists():
        for path in sorted(candidate_root.rglob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                report["errors"].append({"path": str(path), "error": str(exc)})
                continue
            if is_supported_mask_candidate(data):
                continue
            candidate_id = str(data.get("candidate_id") or "")
            if candidate_id:
                legacy_candidate_ids.add(candidate_id)
            for key in ("mask_png", "preview_png"):
                name = data.get(key)
                if not name:
                    continue
                artifact = path.parent / str(name)
                if artifact.exists():
                    report["artifact_png_deleted"] += 1
                    if apply:
                        artifact.unlink()
            report["candidate_json_deleted"] += 1
            if apply:
                path.unlink()

    if review_root.exists() and legacy_candidate_ids:
        for path in sorted(review_root.rglob("review.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                report["errors"].append({"path": str(path), "error": str(exc)})
                continue
            if str(data.get("candidate_id") or "") in legacy_candidate_ids:
                report["review_json_deleted"] += 1
                if apply:
                    path.unlink()

    if apply:
        for root in (candidate_root, review_root):
            if not root.exists():
                continue
            dirs = sorted([p for p in root.rglob("*") if p.is_dir()], key=lambda p: len(p.parts), reverse=True)
            for directory in dirs:
                try:
                    next(directory.iterdir())
                    continue
                except StopIteration:
                    directory.rmdir()
                    report["empty_dirs_removed"] += 1
                except Exception as exc:
                    report["errors"].append({"path": str(directory), "error": str(exc)})

    report["legacy_candidate_ids"] = sorted(legacy_candidate_ids)
    report_dir = dataset_root / "state" / "migrations" / f"{_timestamp()}_purge_legacy_mask_candidates"
    if apply:
        atomic_write_json(report_dir / "report.json", report)
    return report


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = purge_legacy_mask_candidates(args.dataset_root, apply=args.apply)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
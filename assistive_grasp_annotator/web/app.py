"""FastAPI application for the intranet collaboration UI."""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from fastapi import (
    BackgroundTasks,
    Cookie,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from assistive_grasp_annotator.tools.export_obb_teacher import export_obb_teacher_labels
from assistive_grasp_annotator.tools.export_yolo import export_yolo_labels
from assistive_grasp_annotator.tools.export_yolo_angle import export_yolo_angle_labels
from assistive_grasp_annotator.tools.validators import validate_annotation
from assistive_grasp_annotator.web.config import WebConfig
from assistive_grasp_annotator.web.datasets import DatasetError, DatasetService, DatasetValidationError, MaskGenerationError
from assistive_grasp_annotator.web.ids import decode_image_id
from assistive_grasp_annotator.web.schemas import (
    ClassesRequest,
    CompleteChunkedDatasetUploadRequest,
    CompleteChunkedImageUploadRequest,
    CreateDatasetRequest,
    ExportRequest,
    HeartbeatRequest,
    LoginRequest,
    MaskReviewRequest,
    OpenDatasetRequest,
    RenameDatasetRequest,
    ReleaseLockRequest,
    SaveAnnotationRequest,
    ValidateRequest,
)
from assistive_grasp_annotator.web.state import StateStore
from assistive_grasp_annotator.web.uploads import ChunkUploadService, UploadError


USER_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30


def _decode_user_value(value: str | None) -> str:
    if not value:
        return ""
    return unquote(value).strip()


def create_app(config: WebConfig | None = None) -> FastAPI:
    config = config or WebConfig.from_env()
    config.ensure_dirs()
    store = StateStore(config.state_db)
    datasets = DatasetService(config, store)
    uploads = ChunkUploadService(config.state_db.parent / "upload_chunks")

    app = FastAPI(title="AssistiveGraspAnnotator Web", version="0.1.0")
    app.state.config = config
    app.state.store = store
    app.state.datasets = datasets
    app.state.uploads = uploads

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def current_user(
        aga_user: str | None = Cookie(default=None),
        x_aga_user: str | None = Header(default=None),
    ) -> str:
        user = _decode_user_value(x_aga_user) or _decode_user_value(aga_user)
        if not user:
            raise HTTPException(status_code=401, detail="Login required")
        return user

    def dataset_or_404(dataset_id: str):
        try:
            return datasets.get_dataset(dataset_id)
        except DatasetError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def request_file_refs(files: list[Any]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for file in files:
            refs.append(file.model_dump() if hasattr(file, "model_dump") else file.dict())
        return refs

    @app.post("/api/login")
    def login(payload: LoginRequest, response: Response) -> dict[str, Any]:
        username = payload.username.strip()
        if not username:
            raise HTTPException(status_code=422, detail="username is required")
        response.set_cookie(
            "aga_user",
            quote(username),
            httponly=False,
            samesite="lax",
            max_age=USER_COOKIE_MAX_AGE_SECONDS,
        )
        return {"username": username}

    @app.get("/api/roots")
    def roots() -> dict[str, Any]:
        return {"roots": datasets.roots(), "datasets": datasets.list_datasets()}

    @app.get("/api/datasets")
    def list_datasets() -> dict[str, Any]:
        return {"datasets": datasets.list_datasets()}

    @app.post("/api/datasets")
    def create_dataset(payload: CreateDatasetRequest, user: str = Depends(current_user)) -> dict[str, Any]:
        try:
            meta = datasets.create_dataset(payload.name, payload.camera_name, payload.classes)
        except (DatasetError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.log_audit(meta["dataset_id"], None, user, "create_dataset", {"name": payload.name})
        return meta

    @app.post("/api/datasets/open")
    def open_dataset(payload: OpenDatasetRequest, user: str = Depends(current_user)) -> dict[str, Any]:
        try:
            meta = datasets.open_dataset(payload.path, "server")
        except (DatasetError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.log_audit(meta["dataset_id"], None, user, "open_dataset", {"path": payload.path})
        return meta

    @app.post("/api/datasets/upload")
    def upload_dataset(
        user: str = Depends(current_user),
        name: str = Form(...),
        camera_name: str = Form("camera_1"),
        classes_json: str = Form("[]"),
        upload_batch_id: str | None = Form(None),
        files: list[UploadFile] = File(...),
    ) -> dict[str, Any]:
        batch_scope = "dataset:create"
        if upload_batch_id:
            batch_status, batch_result = store.start_upload_batch(batch_scope, upload_batch_id, user)
            if batch_status == "done" and batch_result is not None:
                return batch_result
            if batch_status == "running":
                raise HTTPException(status_code=409, detail="Upload batch is already in progress")
        try:
            meta = datasets.upload_dataset(name, camera_name, classes_json, files)
        except (DatasetError, ValueError) as exc:
            if upload_batch_id:
                store.finish_upload_batch(batch_scope, upload_batch_id, "failed", {}, str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.log_audit(meta["dataset_id"], None, user, "upload_dataset", {"name": name, "files": len(files)})
        if upload_batch_id:
            store.finish_upload_batch(batch_scope, upload_batch_id, "done", meta)
        return meta

    @app.post("/api/uploads/chunk")
    def upload_chunk(
        user: str = Depends(current_user),
        session_id: str = Form(...),
        file_id: str = Form(...),
        filename: str = Form(...),
        chunk_index: int = Form(...),
        total_chunks: int = Form(...),
        chunk: UploadFile = File(...),
    ) -> dict[str, Any]:
        try:
            result = uploads.save_chunk(session_id, file_id, filename, chunk_index, total_chunks, chunk)
        except UploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result["user"] = user
        return result

    @app.post("/api/datasets/upload-chunked/complete")
    def complete_chunked_dataset_upload(
        payload: CompleteChunkedDatasetUploadRequest,
        user: str = Depends(current_user),
    ) -> dict[str, Any]:
        batch_scope = "dataset:create"
        batch_status, batch_result = store.start_upload_batch(batch_scope, payload.upload_batch_id, user)
        if batch_status == "done" and batch_result is not None:
            return batch_result
        if batch_status == "running":
            raise HTTPException(status_code=409, detail="Upload batch is already in progress")
        try:
            assembled = uploads.assemble_files(payload.session_id, request_file_refs(payload.files))
            meta = datasets.upload_dataset_from_assembled(payload.name, payload.camera_name, payload.classes, assembled)
        except (DatasetError, UploadError, ValueError) as exc:
            store.finish_upload_batch(batch_scope, payload.upload_batch_id, "failed", {}, str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        uploads.cleanup_session(payload.session_id)
        store.log_audit(meta["dataset_id"], None, user, "upload_dataset_chunked", {"name": payload.name, "files": len(payload.files)})
        store.finish_upload_batch(batch_scope, payload.upload_batch_id, "done", meta)
        return meta

    @app.get("/api/datasets/{dataset_id}")
    def get_dataset(dataset_id: str) -> dict[str, Any]:
        row, dataset = dataset_or_404(dataset_id)
        return dataset.metadata(dataset_id, row["source"], row["name"])

    @app.get("/api/datasets/{dataset_id}/stats")
    def dataset_stats(dataset_id: str) -> dict[str, Any]:
        _, dataset = dataset_or_404(dataset_id)
        return dataset.stats()

    @app.patch("/api/datasets/{dataset_id}")
    def rename_dataset(
        dataset_id: str,
        payload: RenameDatasetRequest,
        user: str = Depends(current_user),
    ) -> dict[str, Any]:
        try:
            meta = datasets.rename_dataset(dataset_id, payload.name)
        except DatasetError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        store.log_audit(dataset_id, None, user, "rename_dataset", {"name": payload.name})
        return meta

    @app.delete("/api/datasets/{dataset_id}")
    def delete_dataset(dataset_id: str, user: str = Depends(current_user)) -> dict[str, Any]:
        try:
            deleted = datasets.delete_dataset(dataset_id)
        except DatasetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.log_audit(dataset_id, None, user, "delete_dataset", deleted)
        return {"deleted": deleted}

    @app.put("/api/datasets/{dataset_id}/classes")
    def update_classes(
        dataset_id: str,
        payload: ClassesRequest,
        user: str = Depends(current_user),
    ) -> dict[str, Any]:
        row, dataset = dataset_or_404(dataset_id)
        try:
            dataset.save_classes(payload.classes)
        except DatasetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.log_audit(dataset_id, None, user, "update_classes", {"class_count": len(payload.classes)})
        return dataset.metadata(dataset_id, row["source"], row["name"])

    @app.get("/api/datasets/{dataset_id}/images")
    def list_images(
        dataset_id: str,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> dict[str, Any]:
        _, dataset = dataset_or_404(dataset_id)
        entries = dataset.list_images(status)
        limit = max(1, min(limit, 5000))
        offset = max(0, offset)
        page = entries[offset : offset + limit]
        image_ids = [entry.image_id for entry in page]
        locks = store.locks_for_images(dataset_id, image_ids)
        items = [
            entry.to_dict((lock.public_dict() if (lock := locks.get(entry.image_id)) else None))
            for entry in page
        ]
        return {"items": items, "total": len(entries), "offset": offset, "limit": limit}

    @app.post("/api/datasets/{dataset_id}/images/upload")
    def upload_images_to_dataset(
        dataset_id: str,
        user: str = Depends(current_user),
        upload_batch_id: str | None = Form(None),
        files: list[UploadFile] = File(...),
    ) -> dict[str, Any]:
        row, dataset = dataset_or_404(dataset_id)
        batch_scope = f"dataset:{dataset_id}:images"
        if upload_batch_id:
            batch_status, batch_result = store.start_upload_batch(batch_scope, upload_batch_id, user)
            if batch_status == "done" and batch_result is not None:
                return batch_result
            if batch_status == "running":
                raise HTTPException(status_code=409, detail="Upload batch is already in progress")
        try:
            copied = dataset.add_uploaded_images(files)
        except DatasetError as exc:
            if upload_batch_id:
                store.finish_upload_batch(batch_scope, upload_batch_id, "failed", {}, str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.log_audit(dataset_id, None, user, "upload_images", {"files": copied})
        datasets.clear_cache_for(dataset.root)
        result = {
            "added": copied,
            "dataset": dataset.metadata(dataset_id, row["source"], row["name"]),
        }
        if upload_batch_id:
            store.finish_upload_batch(batch_scope, upload_batch_id, "done", result)
        return result

    @app.post("/api/datasets/{dataset_id}/images/upload-chunked/complete")
    def complete_chunked_image_upload(
        dataset_id: str,
        payload: CompleteChunkedImageUploadRequest,
        user: str = Depends(current_user),
    ) -> dict[str, Any]:
        row, dataset = dataset_or_404(dataset_id)
        batch_scope = f"dataset:{dataset_id}:images"
        batch_status, batch_result = store.start_upload_batch(batch_scope, payload.upload_batch_id, user)
        if batch_status == "done" and batch_result is not None:
            return batch_result
        if batch_status == "running":
            raise HTTPException(status_code=409, detail="Upload batch is already in progress")
        try:
            assembled = uploads.assemble_files(payload.session_id, request_file_refs(payload.files))
            copied = dataset.add_assembled_images(assembled)
        except (DatasetError, UploadError, ValueError) as exc:
            store.finish_upload_batch(batch_scope, payload.upload_batch_id, "failed", {}, str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        uploads.cleanup_session(payload.session_id)
        result = {
            "added": copied,
            "dataset": dataset.metadata(dataset_id, row["source"], row["name"]),
        }
        store.log_audit(dataset_id, None, user, "upload_images_chunked", {"files": copied})
        store.finish_upload_batch(batch_scope, payload.upload_batch_id, "done", result)
        return result

    @app.get("/api/datasets/{dataset_id}/images/{image_id}/file")
    def image_file(dataset_id: str, image_id: str) -> FileResponse:
        _, dataset = dataset_or_404(dataset_id)
        try:
            path = dataset.image_path_for_id(image_id)
        except DatasetError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path)

    @app.get("/api/datasets/{dataset_id}/images/{image_id}/annotation")
    def get_annotation(dataset_id: str, image_id: str) -> dict[str, Any]:
        _, dataset = dataset_or_404(dataset_id)
        try:
            payload = dataset.annotation_payload(image_id)
        except DatasetError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        lock = store.lock_for_image(dataset_id, image_id)
        payload["lock"] = lock.public_dict() if lock else None
        return payload

    @app.get("/api/datasets/{dataset_id}/images/{image_id}/mask-review")
    def get_mask_review(dataset_id: str, image_id: str) -> dict[str, Any]:
        _, dataset = dataset_or_404(dataset_id)
        try:
            return dataset.mask_review_payload(image_id)
        except DatasetError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/datasets/{dataset_id}/images/{image_id}/objects/{instance_id}/mask-candidate")
    def create_mask_candidate(
        dataset_id: str,
        image_id: str,
        instance_id: int,
        user: str = Depends(current_user),
    ) -> dict[str, Any]:
        _, dataset = dataset_or_404(dataset_id)
        try:
            candidate = dataset.generate_mask_candidate(image_id, instance_id)
        except MaskGenerationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except DatasetError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        store.log_audit(dataset_id, image_id, user, "generate_mask_candidate", {"instance_id": instance_id})
        return candidate

    @app.put("/api/datasets/{dataset_id}/images/{image_id}/objects/{instance_id}/mask-review")
    def save_mask_review(
        dataset_id: str,
        image_id: str,
        instance_id: int,
        payload: MaskReviewRequest,
        user: str = Depends(current_user),
    ) -> dict[str, Any]:
        _, dataset = dataset_or_404(dataset_id)
        try:
            review = dataset.save_mask_review(image_id, instance_id, user, payload.model_dump())
        except DatasetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.log_audit(dataset_id, image_id, user, "save_mask_review", {"instance_id": instance_id, "score": review["score"]})
        return review

    @app.delete("/api/datasets/{dataset_id}/images/{image_id}/objects/{instance_id}/mask-review")
    def clear_mask_review(
        dataset_id: str,
        image_id: str,
        instance_id: int,
        user: str = Depends(current_user),
    ) -> dict[str, Any]:
        _, dataset = dataset_or_404(dataset_id)
        try:
            cleared = dataset.clear_mask_review(image_id, instance_id)
        except DatasetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.log_audit(dataset_id, image_id, user, "clear_mask_review", {"instance_id": instance_id})
        return cleared

    @app.get("/api/datasets/{dataset_id}/images/{image_id}/objects/{instance_id}/mask-candidate/preview")
    def mask_candidate_preview(dataset_id: str, image_id: str, instance_id: int) -> FileResponse:
        _, dataset = dataset_or_404(dataset_id)
        try:
            path = dataset.mask_candidate_preview_path(image_id, instance_id)
        except DatasetError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path, media_type="image/png")

    @app.delete("/api/datasets/{dataset_id}/images/{image_id}")
    def delete_image(dataset_id: str, image_id: str, user: str = Depends(current_user)) -> dict[str, Any]:
        row, dataset = dataset_or_404(dataset_id)
        lock = store.lock_for_image(dataset_id, image_id)
        if lock and lock.user != user:
            raise HTTPException(status_code=423, detail=f"Image is locked by {lock.user}")
        try:
            deleted = dataset.delete_image(image_id)
        except DatasetError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if lock and lock.user == user:
            store.release_image_lock_for_user(dataset_id, image_id, user)
        store.log_audit(dataset_id, image_id, user, "delete_image", deleted)
        return {"deleted": deleted, "dataset": dataset.metadata(dataset_id, row["source"], row["name"])}

    @app.put("/api/datasets/{dataset_id}/images/{image_id}/annotation")
    def save_annotation(
        dataset_id: str,
        image_id: str,
        payload: SaveAnnotationRequest,
        user: str = Depends(current_user),
    ) -> dict[str, Any]:
        _, dataset = dataset_or_404(dataset_id)
        if not store.verify_lock(dataset_id, image_id, payload.lock_id, payload.lock_token, user):
            raise HTTPException(status_code=423, detail="A valid edit lock is required")
        try:
            saved = dataset.save_annotation(image_id, payload.annotation, payload.etag)
        except DatasetValidationError as exc:
            raise HTTPException(status_code=400, detail={"validation": {"valid": False, **exc.validation}}) from exc
        except DatasetError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        store.release_lock(payload.lock_id, payload.lock_token, user)
        store.log_audit(dataset_id, image_id, user, "save_annotation", {"object_count": len(saved["annotation"]["objects"])})
        saved["lock"] = None
        return saved

    @app.post("/api/datasets/{dataset_id}/images/{image_id}/lock")
    def acquire_lock(dataset_id: str, image_id: str, user: str = Depends(current_user)) -> dict[str, Any]:
        _, dataset = dataset_or_404(dataset_id)
        try:
            image_key = decode_image_id(image_id)
            dataset.image_path_for_id(image_id)
        except (DatasetError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        acquired, lock = store.acquire_lock(dataset_id, image_id, image_key, user, config.lock_ttl_seconds)
        if not acquired:
            raise HTTPException(status_code=423, detail=lock.public_dict())
        data = lock.public_dict()
        data["lock_token"] = lock.token
        store.log_audit(dataset_id, image_id, user, "acquire_lock")
        return data

    @app.post("/api/locks/{lock_id}/heartbeat")
    def heartbeat(lock_id: str, payload: HeartbeatRequest, user: str = Depends(current_user)) -> dict[str, Any]:
        lock = store.heartbeat_lock(lock_id, payload.lock_token, user, config.lock_ttl_seconds)
        if not lock:
            raise HTTPException(status_code=404, detail="Lock not found")
        data = lock.public_dict()
        data["lock_token"] = lock.token
        return data

    @app.delete("/api/locks/{lock_id}")
    def release_lock(lock_id: str, payload: ReleaseLockRequest, user: str = Depends(current_user)) -> dict[str, Any]:
        released = store.release_lock(lock_id, payload.lock_token, user)
        return {"released": released}

    @app.post("/api/datasets/{dataset_id}/validate")
    def validate(dataset_id: str, payload: ValidateRequest) -> dict[str, Any]:
        _, dataset = dataset_or_404(dataset_id)
        targets = []
        if payload.image_id:
            try:
                targets = [dataset.image_path_for_id(payload.image_id)]
            except DatasetError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        else:
            targets = dataset.image_paths
        errors = []
        warnings = []
        for path in targets:
            key = dataset._make_image_key(path)
            report = dataset.validate_annotation_payload(path)
            for err in report["errors"]:
                errors.append({**err, "image_key": err.get("image_key", key)})
            for warning in report["warnings"]:
                warnings.append({**warning, "image_key": warning.get("image_key", key)})
        return {"valid": not errors, "errors": errors, "warnings": warnings}

    def cleanup_export_files(temp_dir: Path) -> None:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

    STORE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".npz"}

    def _zip_compress_type(filepath: Path) -> int:
        return zipfile.ZIP_STORED if filepath.suffix.lower() in STORE_EXTENSIONS else zipfile.ZIP_DEFLATED

    def run_export_job(job_id: str, dataset_id: str, export_type: str, map_size: int) -> None:
        _, dataset_dataset = datasets.get_dataset(dataset_id)
        dataset_name = dataset_dataset.root.name
        tmp_dir = Path(tempfile.mkdtemp(prefix=f"aga_export_{export_type}_"))
        try:
            store.update_job(job_id, "running", "Export running")

            if export_type == "yolo":
                exported, errors = export_yolo_labels(dataset_dataset, tmp_dir)
            elif export_type == "yolo_angle":
                exported, errors = export_yolo_angle_labels(dataset_dataset, tmp_dir)
            elif export_type == "obb_teacher":
                exported, errors = export_obb_teacher_labels(dataset_dataset, tmp_dir)
            else:
                raise ValueError(f"Unsupported export type: {export_type}")

            zip_filename = f"{dataset_name}_{export_type}.zip"
            zip_path = tmp_dir / zip_filename
            arc_root = f"{dataset_name}_{export_type}"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                # 1. Add export output files from temp dir
                for file_path in tmp_dir.rglob("*"):
                    if file_path.is_file() and file_path != zip_path:
                        arcname = f"{arc_root}/{file_path.relative_to(tmp_dir)}"
                        zf.write(file_path, arcname, _zip_compress_type(file_path))

                # 2. Add original images (directly from source, no copy)
                image_arc_root = f"{arc_root}/images"
                for img_path in dataset_dataset.image_paths:
                    image_key = dataset_dataset._make_image_key(img_path)
                    zf.write(
                        img_path,
                        f"{image_arc_root}/{image_key}",
                        _zip_compress_type(img_path),
                    )

                # 3. Add classes.yaml if it exists
                if dataset_dataset.classes_path and dataset_dataset.classes_path.exists():
                    zf.write(
                        dataset_dataset.classes_path,
                        f"{arc_root}/classes.yaml",
                        zipfile.ZIP_DEFLATED,
                    )

            status = "done" if errors == 0 else "done_with_errors"
            store.update_job(
                job_id,
                status,
                f"Exported {exported} item(s), {errors} error(s)",
                {"exported": exported, "errors": errors, "zip_path": str(zip_path)},
            )
        except Exception as exc:
            cleanup_export_files(tmp_dir)
            store.update_job(job_id, "failed", str(exc), {})

    @app.post("/api/datasets/{dataset_id}/exports")
    def create_export(
        dataset_id: str,
        payload: ExportRequest,
        background_tasks: BackgroundTasks,
        user: str = Depends(current_user),
    ) -> dict[str, Any]:
        dataset_or_404(dataset_id)
        job = store.create_job(dataset_id, payload.export_type)
        store.log_audit(dataset_id, None, user, "create_export", {"export_type": payload.export_type})
        background_tasks.add_task(
            run_export_job,
            job["id"],
            dataset_id,
            payload.export_type,
            payload.map_size,
        )
        return job

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    @app.get("/api/jobs/{job_id}/download")
    def download_job_export(
        job_id: str,
        background_tasks: BackgroundTasks,
    ) -> FileResponse:
        job = store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["status"] not in ("done", "done_with_errors"):
            raise HTTPException(
                status_code=400,
                detail=f"Job status is '{job['status']}', must be 'done' or 'done_with_errors'",
            )
        result = job.get("result") or {}
        zip_path_str = result.get("zip_path")
        if not zip_path_str:
            raise HTTPException(status_code=404, detail="No export file for this job")
        zip_path = Path(zip_path_str)
        if not zip_path.exists():
            raise HTTPException(status_code=404, detail="Export file already cleaned up")

        background_tasks.add_task(cleanup_export_files, zip_path.parent)

        filename = f"{job.get('job_type', 'export')}.zip"
        return FileResponse(
            path=zip_path,
            media_type="application/zip",
            filename=filename,
        )

    dist = config.frontend_dist
    assets_dir = dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/", response_class=HTMLResponse)
    def index() -> Any:
        index_path = dist / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        return HTMLResponse(
            """
            <html><body>
            <h1>AssistiveGraspAnnotator Web</h1>
            <p>Frontend build not found. Run <code>npm install</code> and
            <code>npm run build</code> in <code>web_frontend</code>.</p>
            </body></html>
            """,
            status_code=200,
        )

    @app.get("/{full_path:path}")
    def frontend_fallback(full_path: str, request: Request) -> Any:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        index_path = dist / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        raise HTTPException(status_code=404, detail="Frontend build not found")

    return app


app = create_app()

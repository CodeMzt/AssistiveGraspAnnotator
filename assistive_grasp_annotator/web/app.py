"""FastAPI application for the intranet collaboration UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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

from assistive_grasp_annotator.tools.export_grasp_roi import export_grasp_rois
from assistive_grasp_annotator.tools.export_target_maps import export_target_maps
from assistive_grasp_annotator.tools.export_yolo import export_yolo_labels
from assistive_grasp_annotator.tools.validators import validate_annotation
from assistive_grasp_annotator.web.config import WebConfig, resolve_allowed_path
from assistive_grasp_annotator.web.datasets import DatasetError, DatasetService
from assistive_grasp_annotator.web.ids import decode_image_id
from assistive_grasp_annotator.web.schemas import (
    ClassesRequest,
    CompleteChunkedDatasetUploadRequest,
    CompleteChunkedImageUploadRequest,
    CreateDatasetRequest,
    ExportRequest,
    HeartbeatRequest,
    LoginRequest,
    OpenDatasetRequest,
    RenameDatasetRequest,
    ReleaseLockRequest,
    SaveAnnotationRequest,
    ValidateRequest,
)
from assistive_grasp_annotator.web.state import StateStore
from assistive_grasp_annotator.web.uploads import ChunkUploadService, UploadError


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
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def current_user(
        aga_user: str | None = Cookie(default=None),
        x_aga_user: str | None = Header(default=None),
    ) -> str:
        user = (aga_user or x_aga_user or "").strip()
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
        response.set_cookie("aga_user", username, httponly=False, samesite="lax")
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
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        page = entries[offset : offset + limit]
        items = []
        for entry in page:
            lock = store.lock_for_image(dataset_id, entry.image_id)
            items.append(entry.to_dict(lock.public_dict() if lock else None))
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
                errors.append({"image_key": key, "message": err})
            for warning in report["warnings"]:
                warnings.append({"image_key": key, "message": warning})
        return {"valid": not errors, "errors": errors, "warnings": warnings}

    def run_export_job(job_id: str, dataset_id: str, export_type: str, output_dir: str | None, map_size: int) -> None:
        try:
            _, dataset = datasets.get_dataset(dataset_id)
            store.update_job(job_id, "running", "Export running")
            if output_dir:
                out_dir = resolve_allowed_path(output_dir, [dataset.root, config.upload_root])
            elif export_type == "yolo":
                out_dir = dataset.root / "generated" / "detector_yolo"
            elif export_type == "grasp_roi":
                out_dir = dataset.root / "generated" / "grasp_roi"
            else:
                out_dir = dataset.root / "generated" / "target_maps"

            if export_type == "yolo":
                exported, errors = export_yolo_labels(dataset, out_dir)
            elif export_type == "grasp_roi":
                exported, errors = export_grasp_rois(dataset, out_dir)
            elif export_type == "target_maps":
                exported, errors = export_target_maps(dataset, out_dir, map_size=map_size)
            else:
                raise ValueError(f"Unsupported export type: {export_type}")
            status = "done" if errors == 0 else "done_with_errors"
            store.update_job(
                job_id,
                status,
                f"Exported {exported} item(s), {errors} error(s)",
                {"exported": exported, "errors": errors, "output_dir": str(out_dir)},
            )
        except Exception as exc:
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
            payload.output_dir,
            payload.map_size,
        )
        return job

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

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

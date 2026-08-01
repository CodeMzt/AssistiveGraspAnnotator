"""Pydantic request models for the web API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)


class OpenDatasetRequest(BaseModel):
    path: str


class CreateDatasetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    camera_name: str = "camera_1"
    classes: list[dict[str, Any]] = Field(default_factory=list)


class RenameDatasetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ChunkedUploadFileRef(BaseModel):
    file_id: str = Field(min_length=1, max_length=160)
    filename: str = Field(min_length=1, max_length=260)
    size: int | None = None


class CompleteChunkedDatasetUploadRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=160)
    upload_batch_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=120)
    camera_name: str = "camera_1"
    classes: list[dict[str, Any]] = Field(default_factory=list)
    files: list[ChunkedUploadFileRef]


class CompleteChunkedImageUploadRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=160)
    upload_batch_id: str = Field(min_length=1, max_length=160)
    files: list[ChunkedUploadFileRef]


class SaveAnnotationRequest(BaseModel):
    lock_id: str
    lock_token: str
    etag: str
    annotation: dict[str, Any]


class HeartbeatRequest(BaseModel):
    lock_token: str


class ReleaseLockRequest(BaseModel):
    lock_token: str


class ValidateRequest(BaseModel):
    image_id: str | None = None


class ClassesRequest(BaseModel):
    classes: list[dict[str, Any]]


class ExportRequest(BaseModel):
    export_type: Literal["yolo", "yolo_angle", "obb_teacher"]


class MaskReviewRequest(BaseModel):
    candidate_id: str | None = None
    score: int = Field(ge=0, le=3)
    review_status: Literal["accepted", "usable", "uncertain", "rejected"] | None = None
    failure_tags: list[str] = Field(default_factory=list)
    notes: str = ""

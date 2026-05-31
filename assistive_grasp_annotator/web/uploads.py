"""Chunked upload staging for browser uploads behind small reverse-proxy limits."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class UploadError(ValueError):
    pass


@dataclass(frozen=True)
class AssembledUpload:
    filename: str
    path: Path


def _safe_component(value: str, fallback: str = "item") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._")
    return cleaned or fallback


class ChunkUploadService:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _session_dir(self, session_id: str) -> Path:
        return self.root / _safe_component(session_id, "session")

    def _file_dir(self, session_id: str, file_id: str) -> Path:
        return self._session_dir(session_id) / _safe_component(file_id, "file")

    def save_chunk(
        self,
        session_id: str,
        file_id: str,
        filename: str,
        chunk_index: int,
        total_chunks: int,
        upload_file: Any,
    ) -> dict[str, Any]:
        if total_chunks <= 0:
            raise UploadError("total_chunks must be positive")
        if chunk_index < 0 or chunk_index >= total_chunks:
            raise UploadError("chunk_index is outside total_chunks")

        file_dir = self._file_dir(session_id, file_id)
        chunks_dir = file_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "file_id": file_id,
            "filename": Path(filename).name,
            "total_chunks": total_chunks,
        }
        with open(file_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f)

        target = chunks_dir / f"{chunk_index:06d}.part"
        with open(target, "wb") as f:
            shutil.copyfileobj(upload_file.file, f)

        return {
            "session_id": session_id,
            "file_id": file_id,
            "filename": meta["filename"],
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
            "received": True,
        }

    def assemble_files(self, session_id: str, files: list[dict[str, Any]]) -> list[AssembledUpload]:
        assembled: list[AssembledUpload] = []
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            raise UploadError("Upload session was not found")

        assembled_dir = session_dir / "assembled"
        assembled_dir.mkdir(parents=True, exist_ok=True)

        for item in files:
            file_id = str(item.get("file_id", "")).strip()
            filename = Path(str(item.get("filename", "")).strip()).name
            if not file_id or not filename:
                raise UploadError("Each uploaded file requires file_id and filename")

            file_dir = self._file_dir(session_id, file_id)
            meta_path = file_dir / "meta.json"
            if not meta_path.exists():
                raise UploadError(f"Missing chunks for {filename}")
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            total_chunks = int(meta.get("total_chunks", 0))
            if total_chunks <= 0:
                raise UploadError(f"Invalid chunk metadata for {filename}")

            chunks_dir = file_dir / "chunks"
            missing = [index for index in range(total_chunks) if not (chunks_dir / f"{index:06d}.part").exists()]
            if missing:
                raise UploadError(f"Missing {len(missing)} chunk(s) for {filename}")

            suffix = Path(filename).suffix.lower()
            target = assembled_dir / f"{_safe_component(file_id, 'file')}{suffix}"
            temp_target = target.with_suffix(target.suffix + ".tmp")
            with open(temp_target, "wb") as out:
                for index in range(total_chunks):
                    with open(chunks_dir / f"{index:06d}.part", "rb") as part:
                        shutil.copyfileobj(part, out)
            temp_target.replace(target)
            assembled.append(AssembledUpload(filename=filename, path=target))

        return assembled

    def cleanup_session(self, session_id: str) -> None:
        session_dir = self._session_dir(session_id)
        if session_dir.exists():
            shutil.rmtree(session_dir, ignore_errors=True)

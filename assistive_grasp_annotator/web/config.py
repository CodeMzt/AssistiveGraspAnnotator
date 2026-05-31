"""Runtime configuration for the lightweight web server."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _split_paths(value: str) -> list[Path]:
    parts: list[str] = []
    for chunk in value.split(os.pathsep):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return [Path(p).expanduser().resolve() for p in parts]


@dataclass(frozen=True)
class WebConfig:
    dataset_roots: list[Path]
    upload_root: Path
    state_db: Path
    lock_ttl_seconds: int
    frontend_dist: Path

    @staticmethod
    def from_env() -> "WebConfig":
        cwd = Path.cwd().resolve()
        roots_env = os.environ.get("AGA_DATASET_ROOTS", "")
        dataset_roots = _split_paths(roots_env) if roots_env.strip() else [cwd]

        upload_root = Path(os.environ.get("AGA_UPLOAD_ROOT", cwd / ".aga_uploads")).expanduser().resolve()
        state_db = Path(os.environ.get("AGA_STATE_DB", cwd / ".aga_state.sqlite3")).expanduser().resolve()
        frontend_dist = Path(
            os.environ.get("AGA_FRONTEND_DIST", cwd / "web_frontend" / "dist")
        ).expanduser().resolve()
        ttl = int(os.environ.get("AGA_LOCK_TTL_SECONDS", "900"))

        return WebConfig(
            dataset_roots=dataset_roots,
            upload_root=upload_root,
            state_db=state_db,
            lock_ttl_seconds=ttl,
            frontend_dist=frontend_dist,
        )

    def ensure_dirs(self) -> None:
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.state_db.parent.mkdir(parents=True, exist_ok=True)


def resolve_allowed_path(path: str | Path, roots: list[Path]) -> Path:
    candidate = Path(path).expanduser().resolve()
    for root in roots:
        root = root.resolve()
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            if candidate == root:
                return candidate
    raise ValueError(f"Path is outside configured dataset roots: {candidate}")


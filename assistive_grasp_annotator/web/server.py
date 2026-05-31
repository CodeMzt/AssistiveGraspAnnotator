"""Command line entrypoint for the web collaboration server."""

from __future__ import annotations

import os

import uvicorn


def main() -> int:
    host = os.environ.get("AGA_HOST", "0.0.0.0")
    port = int(os.environ.get("AGA_PORT", "8000"))
    uvicorn.run("assistive_grasp_annotator.web.app:app", host=host, port=port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


"""URL-safe identifiers for image keys."""

from __future__ import annotations

import base64


def encode_image_id(image_key: str) -> str:
    raw = image_key.encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_image_id(image_id: str) -> str:
    if not image_id:
        raise ValueError("image_id is empty")
    padding = "=" * (-len(image_id) % 4)
    return base64.urlsafe_b64decode((image_id + padding).encode("ascii")).decode("utf-8")


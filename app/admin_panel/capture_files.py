"""Safe access to saved capture images."""

from __future__ import annotations

from pathlib import Path

UNKNOWN_FACE_DIR = Path(__file__).resolve().parents[2] / "data" / "unknown_faces"


def resolve_capture_image(image_path: str) -> Path | None:
    """The file for a capture, only if it exists inside the capture folder."""
    try:
        path = Path(image_path).resolve()
        path.relative_to(UNKNOWN_FACE_DIR.resolve())
    except (ValueError, OSError):
        return None
    return path if path.is_file() else None


def delete_capture_image(image_path: str) -> bool:
    path = resolve_capture_image(image_path)
    if path is None:
        return False
    path.unlink(missing_ok=True)
    return True

"""How a capture is shown to staff: no server paths, web-match links only for permitted roles."""

from __future__ import annotations

from app.admin_panel import permissions
from app.admin_panel.capture_files import resolve_capture_image
from app.face_schemas import CaptureRead
from app.models import UnknownFaceCapture


def capture_view(capture: UnknownFaceCapture, role: str) -> dict:
    data = CaptureRead.model_validate(capture).model_dump(mode="json")
    data.pop("image_path", None)
    data["has_image"] = resolve_capture_image(capture.image_path) is not None
    if not permissions.can_see_web_links(role):
        for match in data["web_matches"]:
            match["source_url"] = None
            match["thumbnail_base64"] = None
    return data

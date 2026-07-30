"""Reverse face search on the public web.

Given a face image, return the top candidate matches from the internet
(source URL + similarity score + thumbnail). Used only when a face does NOT
match anyone already in our gallery, to help a human identify the visitor.

Default provider is FaceCheck.ID (https://facecheck.id/en/Face-Search/API):
  1. POST the image to /api/upload_pic  -> get an id_search
  2. POST id_search to /api/search      -> poll until results are ready

The provider is optional. If it is disabled or no API token is set, the
functions return an empty list instead of raising, so the kiosk keeps working
and the human reviewer just sees "no web matches".
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass

import httpx

from app.config import settings

FACECHECK_SITE = "https://facecheck.id"
UPLOAD_TIMEOUT_SECONDS = 30
SEARCH_TIMEOUT_SECONDS = 30
MAX_POLL_SECONDS = 60


class WebFaceSearchUnavailable(RuntimeError):
    """Raised when the provider is disabled or not configured."""


@dataclass(frozen=True)
class WebFaceMatch:
    rank: int
    source_url: str
    score: float | None
    thumbnail_base64: str | None
    provider: str


def is_enabled() -> bool:
    return bool(
        settings.face_web_search_enabled
        and settings.face_web_search_provider == "facecheck"
        and settings.facecheck_api_token
    )


def search_web_faces(image_bytes: bytes, *, limit: int = 3) -> list[WebFaceMatch]:
    """Return up to `limit` web matches. Empty list if disabled or none found."""
    if not is_enabled():
        raise WebFaceSearchUnavailable(
            "Web face search is disabled or FACECHECK_API_TOKEN is not set."
        )
    return _search_facecheck(image_bytes, limit=limit)


def _search_facecheck(image_bytes: bytes, *, limit: int) -> list[WebFaceMatch]:
    headers = {"accept": "application/json", "Authorization": settings.facecheck_api_token}
    testing_mode = settings.face_web_search_testing_mode

    with httpx.Client(timeout=UPLOAD_TIMEOUT_SECONDS) as client:
        upload = client.post(
            f"{FACECHECK_SITE}/api/upload_pic",
            headers=headers,
            files={"images": ("face.jpg", image_bytes, "image/jpeg"), "id_search": (None, "")},
        ).json()

        if upload.get("error"):
            raise WebFaceSearchUnavailable(
                f"Upload failed: {upload['error']} ({upload.get('code')})"
            )

        id_search = upload["id_search"]
        payload = {
            "id_search": id_search,
            "with_progress": True,
            "status_only": False,
            "demo": testing_mode,
        }

        deadline = time.monotonic() + MAX_POLL_SECONDS
        while True:
            result = client.post(
                f"{FACECHECK_SITE}/api/search",
                headers=headers,
                json=payload,
                timeout=SEARCH_TIMEOUT_SECONDS,
            ).json()

            if result.get("error"):
                raise WebFaceSearchUnavailable(
                    f"Search failed: {result['error']} ({result.get('code')})"
                )

            output = result.get("output")
            if output:
                return _parse_items(output.get("items", []), limit=limit)

            if time.monotonic() > deadline:
                raise WebFaceSearchUnavailable("Web face search timed out.")
            time.sleep(2)


def _parse_items(items: list[dict], *, limit: int) -> list[WebFaceMatch]:
    matches: list[WebFaceMatch] = []
    for rank, item in enumerate(items[:limit], start=1):
        raw_score = item.get("score")
        score = float(raw_score) / 100.0 if isinstance(raw_score, (int, float)) else None
        matches.append(
            WebFaceMatch(
                rank=rank,
                source_url=item.get("url", ""),
                score=score,
                thumbnail_base64=item.get("base64"),
                provider="facecheck",
            )
        )
    return matches


def encode_thumbnail(image_bytes: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")

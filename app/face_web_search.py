"""Reverse face search on the public web.

Given one or more face images of the same person, return the top candidate
matches from the internet (source URL + similarity score + thumbnail). Used
only when a face does NOT match anyone already in our gallery, to help
identify the visitor.

Default provider is FaceCheck.ID (https://facecheck.id/en/Face-Search/API):
  1. POST each image to /api/upload_pic, reusing the same id_search on each
     call after the first -> builds one search bucket from multiple photos
     of the same person, which improves match accuracy over a single frame.
  2. POST the final id_search to /api/search -> poll until results are ready

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
MAX_UPLOAD_IMAGES = 5  # guard against accidentally sending too many frames


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


def search_web_faces(images_bytes: bytes | list[bytes], *, limit: int = 3) -> list[WebFaceMatch]:
    """Return up to `limit` web matches. Empty list if disabled or none found.

    `images_bytes` can be a single image (bytes) or a list of images of the
    same person -- passing multiple frames lets FaceCheck.ID search using
    all of them together, which tends to be more accurate than one photo.
    """
    if not is_enabled():
        raise WebFaceSearchUnavailable(
            "Web face search is disabled or FACECHECK_API_TOKEN is not set."
        )

    if isinstance(images_bytes, (bytes, bytearray)):
        images_list = [bytes(images_bytes)]
    else:
        images_list = list(images_bytes)[:MAX_UPLOAD_IMAGES]

    if not images_list:
        raise WebFaceSearchUnavailable("No images were provided for web face search.")

    return _search_facecheck(images_list, limit=limit)


def _upload_image(client: httpx.Client, headers: dict, image_bytes: bytes, id_search: str) -> str:
    """Upload one image into the search bucket identified by id_search.

    Pass id_search="" on the first upload to start a brand-new search;
    FaceCheck.ID returns the id_search to reuse for subsequent images so
    they all get searched together as photos of the same person.
    """
    upload = client.post(
        f"{FACECHECK_SITE}/api/upload_pic",
        headers=headers,
        files={"images": ("face.jpg", image_bytes, "image/jpeg"), "id_search": (None, id_search)},
    ).json()

    if upload.get("error"):
        raise WebFaceSearchUnavailable(
            f"Upload failed: {upload['error']} ({upload.get('code')})"
        )

    return upload["id_search"]


def _search_facecheck(images_bytes: list[bytes], *, limit: int) -> list[WebFaceMatch]:
    headers = {"accept": "application/json", "Authorization": settings.facecheck_api_token}
    testing_mode = settings.face_web_search_testing_mode

    with httpx.Client(timeout=UPLOAD_TIMEOUT_SECONDS) as client:
        id_search = ""
        for image_bytes in images_bytes:
            id_search = _upload_image(client, headers, image_bytes, id_search)

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
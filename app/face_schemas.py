from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class DetectFaceRequest(BaseModel):
    image_base64: Optional[str] = None
    images_base64: Optional[list[str]] = Field(default=None, min_length=1, max_length=5)
    run_web_search: bool = True


class WebMatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rank: int
    source_url: str
    score: Optional[float] = None
    thumbnail_base64: Optional[str] = None
    provider: str


class CaptureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    capture_id: int
    image_path: str
    best_gallery_score: Optional[float] = None
    status: str
    web_search_status: Optional[str] = None
    linked_visitor_id: Optional[int] = None
    first_seen_at: datetime
    last_seen_at: datetime
    web_matches: list[WebMatchRead] = []


class DetectFaceResponse(BaseModel):
    recognized: bool
    visitor_id: Optional[int] = None
    matched_name: Optional[str] = None
    face_identifier: Optional[str] = None
    confidence: Optional[float] = None
    capture: Optional[CaptureRead] = None


class LinkCaptureRequest(BaseModel):
    visitor_id: Optional[int] = None
    full_name: Optional[str] = Field(default=None, max_length=150)
    mobile_number: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=150)
    visitor_type: Literal["client", "visitor"] = "visitor"
    enroll_face: bool = True

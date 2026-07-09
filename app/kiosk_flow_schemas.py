from datetime import date, datetime, time
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


VisitorType = Literal["client", "visitor"]
RecognitionMethod = Literal["face", "lookup", "manual"]
KioskService = Literal[
    "meeting_room",
    "podcast_studio",
    "tiktok_studio",
    "event",
    "business_center",
    "other",
]
OtherAssistanceReason = Literal[
    "start_company",
    "free_zone_questions",
    "document_creation_renewal",
]


class RecognizeFaceRequest(BaseModel):
    simulate_mobile_number: Optional[str] = Field(default=None, max_length=40)


class RecognizeFaceResponse(BaseModel):
    recognized: bool
    visitor_id: Optional[int] = None


class ProfileLookupRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=150)
    mobile_number: str = Field(..., min_length=1, max_length=40)


class CreateProfileRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=150)
    mobile_number: str = Field(..., min_length=1, max_length=40)
    email: str = Field(..., min_length=1, max_length=150)
    visitor_type: VisitorType
    license_number: Optional[str] = Field(default=None, max_length=80)
    company_name: Optional[str] = Field(default=None, max_length=160)
    company_number: Optional[str] = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def clear_license_for_non_clients(self):
        if self.visitor_type == "visitor":
            self.license_number = None
        return self


class FacialConsentRequest(BaseModel):
    visitor_id: int
    consent_given: bool


class CreateFaceProfileRequest(BaseModel):
    visitor_id: int


class VisitSessionCreate(BaseModel):
    visitor_id: Optional[int] = None
    recognition_method: RecognitionMethod
    current_selected_service: Optional[KioskService] = None
    visit_purpose: Optional[str] = Field(default=None, max_length=160)
    notes: Optional[str] = None


class KioskBookingCreate(BaseModel):
    visitor_id: int
    visit_session_id: Optional[int] = None
    service_type: Literal["meeting_room", "podcast_studio", "tiktok_studio"]
    room_name: Optional[str] = Field(default=None, max_length=120)
    booking_date: date
    booking_time_start: time
    duration_minutes: int = Field(..., gt=0, le=480)


class EventSelectionCreate(BaseModel):
    visitor_id: int
    visit_session_id: Optional[int] = None
    event_id: int


class OtherAssistanceCreate(BaseModel):
    visitor_id: int
    visit_session_id: Optional[int] = None
    reason: OtherAssistanceReason
    notes: Optional[str] = None


class KioskVisitorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    visitor_id: int
    visitor_name: str
    visitor_phone: str
    visitor_email: Optional[str] = None
    visitor_type: VisitorType = "visitor"
    company_name: Optional[str] = None
    company_number: Optional[str] = None
    license_number: Optional[str] = None
    face_consent_given: bool = False
    last_visit_at: Optional[datetime] = None


class KioskBookingRead(BaseModel):
    booking_id: int
    booking_type: str
    booking_name: str
    booking_date: date
    booking_time_start: time
    booking_time_end: time
    zone_id: str
    room_name: str


class KioskEventRead(BaseModel):
    event_id: int
    event_name: str
    event_date: date
    event_time_start: time
    event_time_end: time
    event_location: str
    short_description: str


class KioskPackageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    package_id: int
    package_name: str
    package_description: str
    price_label: Optional[str] = None
    features: str


class VisitSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    visit_session_id: int
    visitor_id: Optional[int] = None
    recognition_method: RecognitionMethod
    is_returning_visitor: bool
    previous_visit_id: Optional[int] = None
    current_selected_service: Optional[str] = None
    visit_purpose: Optional[str] = None
    notes: Optional[str] = None
    check_in_time: datetime

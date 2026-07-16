from datetime import date, datetime, time
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.operating_hours import OPERATING_HOURS_MESSAGE, is_within_operating_hours


# ============================================================
# Shared response schemas
# ============================================================


class SuccessResponse(BaseModel):
    success: bool = True
    message: str
    data: Any = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    success: bool = False
    message: str
    error_code: str
    details: Any = None


# ============================================================
# Admin auth schemas
# ============================================================


class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=80)
    password: str = Field(..., min_length=1, max_length=120)


class AdminLoginResponse(BaseModel):
    username: str
    role: str


# ============================================================
# Zone schemas
# ============================================================


class AdminZoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    zone_id: str
    zone_name: str
    zone_type: str
    is_bookable: bool
    is_closed: bool
    current_map_status: str
    zone_start_time: Optional[time] = None
    zone_end_time: Optional[time] = None
    active_booking_id: Optional[int] = None
    active_booking_name: Optional[str] = None
    active_booking_type: Optional[str] = None
    zone_pulse: bool
    zone_highlight_color: str
    updated_at: datetime


class ZoneClosedResponse(BaseModel):
    zone_id: str
    is_closed: bool


# ============================================================
# Booking schemas
# ============================================================


BookingType = Literal["meeting", "studio", "office"]
BookingStatus = Literal["upcoming", "live", "ended"]


class BookingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    booking_id: int
    visitor_id: Optional[int] = None
    zone_id: str
    booking_type: BookingType
    booking_name: str
    visitor_name: Optional[str] = None
    visitor_phone: Optional[str] = None
    visitor_email: Optional[str] = None
    visitor_is_client: bool = False
    booking_start_date: date
    booking_end_date: date
    booking_date: date
    booking_time_start: time
    booking_time_end: time
    booking_status: BookingStatus


class BookingCreate(BaseModel):
    visitor_id: Optional[int] = None
    zone_id: str = Field(..., min_length=1, max_length=30)
    booking_type: BookingType
    booking_name: str = Field(..., min_length=1, max_length=200)
    visitor_name: Optional[str] = Field(default=None, max_length=150)
    visitor_phone: Optional[str] = Field(default=None, max_length=40)
    visitor_email: Optional[str] = Field(default=None, max_length=150)
    visitor_is_client: bool = False
    booking_start_date: date
    booking_end_date: date
    booking_date: Optional[date] = None
    booking_time_start: time
    booking_time_end: time

    @model_validator(mode="after")
    def validate_date_and_time_range(self):
        if self.booking_end_date < self.booking_start_date:
            raise ValueError("booking_end_date must be on or after booking_start_date")
        if self.booking_time_end <= self.booking_time_start:
            raise ValueError("booking_time_end must be after booking_time_start")
        if not is_within_operating_hours(self.booking_time_start, self.booking_time_end):
            raise ValueError(OPERATING_HOURS_MESSAGE)
        if self.booking_date is None:
            self.booking_date = self.booking_start_date
        return self


class BookingUpdate(BaseModel):
    visitor_id: Optional[int] = None
    zone_id: Optional[str] = Field(default=None, min_length=1, max_length=30)
    booking_type: Optional[BookingType] = None
    booking_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    visitor_name: Optional[str] = Field(default=None, max_length=150)
    visitor_phone: Optional[str] = Field(default=None, max_length=40)
    visitor_email: Optional[str] = Field(default=None, max_length=150)
    visitor_is_client: Optional[bool] = None
    booking_start_date: Optional[date] = None
    booking_end_date: Optional[date] = None
    booking_date: Optional[date] = None
    booking_time_start: Optional[time] = None
    booking_time_end: Optional[time] = None

    @model_validator(mode="after")
    def validate_date_and_time_range_if_complete(self):
        if (
            self.booking_start_date is not None
            and self.booking_end_date is not None
            and self.booking_end_date < self.booking_start_date
        ):
            raise ValueError("booking_end_date must be on or after booking_start_date")
        if (
            self.booking_time_start is not None
            and self.booking_time_end is not None
            and self.booking_time_end <= self.booking_time_start
        ):
            raise ValueError("booking_time_end must be after booking_time_start")
        if (
            self.booking_time_start is not None
            and self.booking_time_end is not None
            and not is_within_operating_hours(self.booking_time_start, self.booking_time_end)
        ):
            raise ValueError(OPERATING_HOURS_MESSAGE)
        return self


# ============================================================
# Visitor schemas
# ============================================================


class VisitorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    visitor_id: int
    visitor_name: str
    visitor_phone: str
    visitor_email: Optional[str] = None
    license_number: Optional[str] = None
    is_existing_client: bool = False
    face_reference_id: Optional[str] = None
    face_consent_given: bool = False
    face_consent_at: Optional[datetime] = None
    lead_source: Optional[
        Literal[
            "admin_visitors_tab",
            "admin_booking_tab",
            "screen_1_booking",
            "screen_2_booking",
            "screen_2_check_in",
            "map_screen",
        ]
    ] = None
    last_visit_at: Optional[datetime] = None
    visit_count: int = 0
    created_at: datetime
    updated_at: datetime


class VisitorCreate(BaseModel):
    visitor_name: str = Field(..., min_length=1, max_length=150)
    visitor_phone: str = Field(..., min_length=1, max_length=40)
    visitor_email: Optional[str] = Field(default=None, max_length=150)
    license_number: Optional[str] = Field(default=None, max_length=80)
    is_existing_client: bool = False
    face_reference_id: Optional[str] = Field(default=None, max_length=120)
    face_consent_given: bool = False
    face_consent_at: Optional[datetime] = None
    lead_source: Optional[
        Literal[
            "admin_visitors_tab",
            "admin_booking_tab",
            "screen_1_booking",
            "screen_2_booking",
            "screen_2_check_in",
            "map_screen",
        ]
    ] = "admin_visitors_tab"


class VisitorUpdate(BaseModel):
    visitor_name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    visitor_phone: Optional[str] = Field(default=None, min_length=1, max_length=40)
    visitor_email: Optional[str] = Field(default=None, max_length=150)
    license_number: Optional[str] = Field(default=None, max_length=80)
    is_existing_client: Optional[bool] = None
    face_reference_id: Optional[str] = Field(default=None, max_length=120)
    face_consent_given: Optional[bool] = None
    face_consent_at: Optional[datetime] = None
    lead_source: Optional[
        Literal[
            "admin_visitors_tab",
            "admin_booking_tab",
            "screen_1_booking",
            "screen_2_booking",
            "screen_2_check_in",
            "map_screen",
        ]
    ] = None


VisitorCheckInStatus = Literal[
    "booking_found",
    "no_booking_found",
    "new_visitor_registered",
    "service_requested",
    "event_selected",
]
VisitorMatchMethod = Literal["phone", "license_number", "face"]
VisitorSelectedService = Literal[
    "meeting_room",
    "podcast_studio",
    "tiktok_studio",
    "event",
    "business_center",
    "other",
]
FaceEnrollmentStatus = Literal["not_enrolled", "enrolled", "failed"]


class VisitorCheckInRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    check_in_id: int
    visitor_id: Optional[int] = None
    visitor_phone: Optional[str] = None
    booking_id: Optional[int] = None
    event_id: Optional[int] = None
    check_in_time: datetime
    check_in_status: VisitorCheckInStatus
    match_method: VisitorMatchMethod
    selected_service: Optional[VisitorSelectedService] = None
    face_enrollment_status: Optional[FaceEnrollmentStatus] = None


class VisitorCheckInCreate(BaseModel):
    visitor_id: Optional[int] = None
    visitor_phone: Optional[str] = Field(default=None, max_length=40)
    booking_id: Optional[int] = None
    event_id: Optional[int] = None
    check_in_status: VisitorCheckInStatus
    match_method: VisitorMatchMethod
    selected_service: Optional[VisitorSelectedService] = None
    face_enrollment_status: Optional[FaceEnrollmentStatus] = None


# ============================================================
# Event schemas
# ============================================================


EventStatus = Literal["upcoming", "live", "ended"]
DEFAULT_EVENT_ZONE_ID = "EVT_1"
DEFAULT_EVENT_LOCATION = "Event Area"


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: int
    zone_id: str
    event_name: str
    event_date: date
    event_time_start: time
    event_time_end: time
    event_location: str
    event_organizer: str
    event_attendee_count: Optional[int] = None
    event_status: EventStatus


class EventCreate(BaseModel):
    zone_id: str = Field(default=DEFAULT_EVENT_ZONE_ID, min_length=1, max_length=30)
    event_name: str = Field(..., min_length=1, max_length=200)
    event_date: date
    event_time_start: time
    event_time_end: time
    event_location: Optional[str] = Field(default=DEFAULT_EVENT_LOCATION, max_length=120)
    event_organizer: str = Field(..., min_length=1, max_length=150)
    event_attendee_count: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_time_range(self):
        if self.event_time_end <= self.event_time_start:
            raise ValueError("event_time_end must be after event_time_start")
        if not is_within_operating_hours(self.event_time_start, self.event_time_end):
            raise ValueError(OPERATING_HOURS_MESSAGE)
        if self.event_location is None or not self.event_location.strip():
            self.event_location = DEFAULT_EVENT_LOCATION
        return self


class EventUpdate(BaseModel):
    zone_id: Optional[str] = Field(default=None, min_length=1, max_length=30)
    event_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    event_date: Optional[date] = None
    event_time_start: Optional[time] = None
    event_time_end: Optional[time] = None
    event_location: Optional[str] = Field(default=None, min_length=1, max_length=120)
    event_organizer: Optional[str] = Field(default=None, min_length=1, max_length=150)
    event_attendee_count: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_time_range_if_complete(self):
        if (
            self.event_time_start is not None
            and self.event_time_end is not None
            and self.event_time_end <= self.event_time_start
        ):
            raise ValueError("event_time_end must be after event_time_start")
        if (
            self.event_time_start is not None
            and self.event_time_end is not None
            and not is_within_operating_hours(self.event_time_start, self.event_time_end)
        ):
            raise ValueError(OPERATING_HOURS_MESSAGE)
        return self


# ============================================================
# Ecosystem schemas
# ============================================================


class EcosystemMetricRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ecosystem_id: int
    snapshot_date: date
    active_companies: int
    active_licenses: int
    recorded_at: datetime


class EcosystemMetricUpdate(BaseModel):
    active_companies: int = Field(..., ge=0)
    active_licenses: int = Field(..., ge=0)
    snapshot_date: Optional[date] = None


# ============================================================
# Live activity schemas
# ============================================================


class LiveActivityMetricRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    snapshot_date: date
    meetings_active: int
    zones_occupied: int
    zones_total: int
    visitors_count: int
    events_today_count: int


class LiveActivityFeedRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    feed_id: str
    occurred_at: datetime
    category: str
    activity_action: str
    zone_id: Optional[str] = None
    zone_name: Optional[str] = None
    zone_status: Optional[str] = None
    event_id: Optional[int] = None
    event_name: Optional[str] = None
    booking_id: Optional[int] = None
    booking_name: Optional[str] = None
    display_message: str

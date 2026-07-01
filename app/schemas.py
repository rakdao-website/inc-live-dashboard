from datetime import date, datetime, time
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    zone_id: str
    booking_type: BookingType
    booking_name: str
    visitor_name: Optional[str] = None
    visitor_phone: Optional[str] = None
    visitor_is_client: bool = False
    booking_date: date
    booking_time_start: time
    booking_time_end: time
    booking_status: BookingStatus


class BookingCreate(BaseModel):
    zone_id: str = Field(..., min_length=1, max_length=30)
    booking_type: BookingType
    booking_name: str = Field(..., min_length=1, max_length=200)
    visitor_name: Optional[str] = Field(default=None, max_length=150)
    visitor_phone: Optional[str] = Field(default=None, max_length=40)
    visitor_is_client: bool = False
    booking_date: date
    booking_time_start: time
    booking_time_end: time

    @model_validator(mode="after")
    def validate_time_range(self):
        if self.booking_time_end <= self.booking_time_start:
            raise ValueError("booking_time_end must be after booking_time_start")
        return self


class BookingUpdate(BaseModel):
    zone_id: Optional[str] = Field(default=None, min_length=1, max_length=30)
    booking_type: Optional[BookingType] = None
    booking_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    visitor_name: Optional[str] = Field(default=None, max_length=150)
    visitor_phone: Optional[str] = Field(default=None, max_length=40)
    visitor_is_client: Optional[bool] = None
    booking_date: Optional[date] = None
    booking_time_start: Optional[time] = None
    booking_time_end: Optional[time] = None

    @model_validator(mode="after")
    def validate_time_range_if_complete(self):
        if (
            self.booking_time_start is not None
            and self.booking_time_end is not None
            and self.booking_time_end <= self.booking_time_start
        ):
            raise ValueError("booking_time_end must be after booking_time_start")
        return self


# ============================================================
# Event schemas
# ============================================================


EventStatus = Literal["upcoming", "live", "ended"]


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
    zone_id: str = Field(..., min_length=1, max_length=30)
    event_name: str = Field(..., min_length=1, max_length=200)
    event_date: date
    event_time_start: time
    event_time_end: time
    event_location: str = Field(default="Event Area", min_length=1, max_length=120)
    event_organizer: str = Field(..., min_length=1, max_length=150)
    event_attendee_count: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_time_range(self):
        if self.event_time_end <= self.event_time_start:
            raise ValueError("event_time_end must be after event_time_start")
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
    top_sector: str
    recorded_at: datetime


class EcosystemMetricUpdate(BaseModel):
    active_companies: int = Field(..., ge=0)
    active_licenses: int = Field(..., ge=0)
    top_sector: str = Field(..., min_length=1, max_length=100)
    snapshot_date: Optional[date] = None


# ============================================================
# Sector schemas
# ============================================================


class SectorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sector_id: int
    sector_name: str
    company_count: int
    source_name: str
    display_order: int


class SectorCreate(BaseModel):
    sector_name: str = Field(..., min_length=1, max_length=100)
    company_count: int = Field(..., ge=0)
    source_name: str = Field(..., min_length=1, max_length=200)
    display_order: int = Field(..., gt=0)


class SectorUpdate(BaseModel):
    sector_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    company_count: Optional[int] = Field(default=None, ge=0)
    source_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    display_order: Optional[int] = Field(default=None, gt=0)


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

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.operating_hours import OPERATING_HOURS_MESSAGE, is_within_operating_hours


class ZoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    zone_id: str
    zone_name: str
    zone_type: str
    is_bookable: bool
    is_closed: bool
    status: str
    pulse: bool


class ActivityItem(BaseModel):
    feed_id: str
    occurred_at: datetime
    category: str
    action: str
    message: str


class ActivityMetricsRead(BaseModel):
    zones_occupied: int
    zones_total: int
    meetings_active: int
    visitors_count: int
    events_today_count: int


class EcosystemMetricRead(BaseModel):
    snapshot_date: date
    active_companies: int
    active_licenses: int


class EventRead(BaseModel):
    event_id: int
    name: str
    date: date
    start: time
    end: time
    location: str
    organizer: str
    attendee_count: int | None
    zone_id: str
    zone_name: str
    status: str


class BookingRead(BaseModel):
    booking_id: int
    booking_type: str
    name: str
    visitor_name: str | None = None
    visitor_phone: str | None = None
    visitor_email: str | None = None
    visitor_is_client: bool = False
    date: date
    start: time
    end: time
    zone_id: str
    zone_name: str
    status: str


class ScreenBookingCreate(BaseModel):
    zone_id: str = Field(..., min_length=1, max_length=30)
    visitor_name: str = Field(..., min_length=1, max_length=150)
    visitor_phone: str = Field(..., min_length=1, max_length=40)
    visitor_email: str | None = Field(default=None, max_length=150)
    visitor_is_client: bool = False
    booking_date: date
    booking_time_start: time
    booking_time_end: time

    @model_validator(mode="after")
    def validate_booking_window(self):
        if self.booking_time_end <= self.booking_time_start:
            raise ValueError("booking_time_end must be after booking_time_start")
        if not is_within_operating_hours(self.booking_time_start, self.booking_time_end):
            raise ValueError(OPERATING_HOURS_MESSAGE)
        return self


class HeaderResponse(BaseModel):
    title: str
    subtitle: str
    screen: str
    date: date
    day: str
    display_date: str
    time: str
    timezone: str
    status: str
    last_updated: datetime

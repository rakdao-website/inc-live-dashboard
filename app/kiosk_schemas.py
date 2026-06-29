from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict


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
    events_today_count: int


class EcosystemMetricRead(BaseModel):
    snapshot_date: date
    active_companies: int
    active_licenses: int
    top_sector: str


class SectorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    sector_id: int
    sector_name: str
    company_count: int
    source_name: str
    display_order: int


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
    date: date
    start: time
    end: time
    zone_id: str
    zone_name: str
    status: str


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

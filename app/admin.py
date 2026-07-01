from datetime import date as DateType
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import (
    AdminZone,
    Booking,
    EcosystemMetric,
    Event,
    LiveActivityFeed,
    LiveActivityMetric,
    LiveBooking,
    LiveEvent,
    Sector,
    Zone,
)
from app.schemas import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminZoneRead,
    BookingCreate,
    BookingRead,
    BookingUpdate,
    EcosystemMetricRead,
    EcosystemMetricUpdate,
    EventCreate,
    EventRead,
    EventUpdate,
    LiveActivityFeedRead,
    LiveActivityMetricRead,
    SectorCreate,
    SectorRead,
    SectorUpdate,
    ZoneClosedResponse,
)


router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
)


def success_response(
    message: str = "Request completed successfully",
    data: Any = None,
) -> dict[str, Any]:
    return {
        "success": True,
        "message": message,
        "data": {} if data is None else data,
    }


def error_response(
    message: str,
    error_code: str,
    details: Any = None,
) -> dict[str, Any]:
    return {
        "success": False,
        "message": message,
        "error_code": error_code,
        "details": details,
    }


def not_found_response(message: str, error_code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=error_response(
            message=message,
            error_code=error_code,
        ),
    )


def bad_request_response(message: str, error_code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=error_response(
            message=message,
            error_code=error_code,
        ),
    )


def conflict_response(message: str, error_code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=error_response(
            message=message,
            error_code=error_code,
        ),
    )


def get_database_current_date(db: Session) -> DateType:
    return db.query(func.current_date()).scalar()


def validate_bookable_open_zone(zone_id: str, db: Session) -> JSONResponse | None:
    zone = db.get(Zone, zone_id)

    if zone is None:
        return not_found_response(
            message="Zone not found",
            error_code="ZONE_NOT_FOUND",
        )

    if not zone.is_bookable:
        return bad_request_response(
            message="Zone is not bookable",
            error_code="ZONE_NOT_BOOKABLE",
        )

    if zone.is_closed:
        return bad_request_response(
            message="Zone is closed",
            error_code="ZONE_CLOSED",
        )

    return None


def is_overlap_error(exc: SQLAlchemyError) -> bool:
    error_text = str(exc).lower()
    return "overlaps" in error_text or "overlap" in error_text


@router.post("/auth/login")
def admin_login(payload: AdminLoginRequest):
    if (
        payload.username != settings.admin_username
        or payload.password != settings.admin_password
    ):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=error_response(
                message="Invalid username or password",
                error_code="INVALID_ADMIN_LOGIN",
            ),
        )

    user = AdminLoginResponse(
        username=settings.admin_username,
        role=settings.admin_role,
    )

    return success_response(
        message="Signed in successfully",
        data=user.model_dump(),
    )


@router.get("/health")
def admin_health_check():
    return success_response(
        message="Admin router is available",
        data={
            "status": "ok",
        },
    )


# ============================================================
# Zones Admin API
# ============================================================


@router.get("/zones")
def list_zones(db: Session = Depends(get_db)):
    zones = (
        db.query(AdminZone)
        .order_by(AdminZone.zone_name)
        .all()
    )

    data = [
        AdminZoneRead.model_validate(zone).model_dump()
        for zone in zones
    ]

    return success_response(
        message="Zones retrieved successfully",
        data=data,
    )


@router.get("/zones/{zone_id}")
def get_zone(zone_id: str, db: Session = Depends(get_db)):
    zone = (
        db.query(AdminZone)
        .filter(AdminZone.zone_id == zone_id)
        .first()
    )

    if zone is None:
        return not_found_response(
            message="Zone not found",
            error_code="ZONE_NOT_FOUND",
        )

    data = AdminZoneRead.model_validate(zone).model_dump()

    return success_response(
        message="Zone retrieved successfully",
        data=data,
    )


@router.patch("/zones/{zone_id}/close")
def close_zone(zone_id: str, db: Session = Depends(get_db)):
    zone = db.get(Zone, zone_id)

    if zone is None:
        return not_found_response(
            message="Zone not found",
            error_code="ZONE_NOT_FOUND",
        )

    zone.is_closed = True
    zone.updated_at = func.current_timestamp()

    db.commit()

    data = ZoneClosedResponse(
        zone_id=zone_id,
        is_closed=True,
    ).model_dump()

    return success_response(
        message="Zone closed successfully",
        data=data,
    )


@router.patch("/zones/{zone_id}/reopen")
def reopen_zone(zone_id: str, db: Session = Depends(get_db)):
    zone = db.get(Zone, zone_id)

    if zone is None:
        return not_found_response(
            message="Zone not found",
            error_code="ZONE_NOT_FOUND",
        )

    zone.is_closed = False
    zone.updated_at = func.current_timestamp()

    db.commit()

    data = ZoneClosedResponse(
        zone_id=zone_id,
        is_closed=False,
    ).model_dump()

    return success_response(
        message="Zone reopened successfully",
        data=data,
    )


# ============================================================
# Ecosystem Metrics Admin API
# ============================================================


@router.get("/ecosystem/current")
def get_current_ecosystem_metrics(db: Session = Depends(get_db)):
    today = get_database_current_date(db)

    metrics = (
        db.query(EcosystemMetric)
        .filter(EcosystemMetric.snapshot_date == today)
        .first()
    )

    if metrics is None:
        metrics = (
            db.query(EcosystemMetric)
            .order_by(EcosystemMetric.snapshot_date.desc())
            .first()
        )

    if metrics is None:
        return not_found_response(
            message="Ecosystem metrics not found",
            error_code="ECOSYSTEM_METRICS_NOT_FOUND",
        )

    data = EcosystemMetricRead.model_validate(metrics).model_dump()

    return success_response(
        message="Ecosystem metrics retrieved successfully",
        data=data,
    )


@router.put("/ecosystem/current")
def update_current_ecosystem_metrics(
    payload: EcosystemMetricUpdate,
    db: Session = Depends(get_db),
):
    target_date = payload.snapshot_date or get_database_current_date(db)

    metrics = (
        db.query(EcosystemMetric)
        .filter(EcosystemMetric.snapshot_date == target_date)
        .first()
    )

    if metrics is None:
        metrics = EcosystemMetric(
            snapshot_date=target_date,
            active_companies=payload.active_companies,
            active_licenses=payload.active_licenses,
            top_sector=payload.top_sector,
        )
        db.add(metrics)
    else:
        metrics.active_companies = payload.active_companies
        metrics.active_licenses = payload.active_licenses
        metrics.top_sector = payload.top_sector
        metrics.recorded_at = func.current_timestamp()

    db.commit()
    db.refresh(metrics)

    data = EcosystemMetricRead.model_validate(metrics).model_dump()

    return success_response(
        message="Ecosystem metrics updated successfully",
        data=data,
    )


# ============================================================
# Sector Management Admin API
# ============================================================


@router.get("/sectors")
def list_sectors(db: Session = Depends(get_db)):
    sectors = (
        db.query(Sector)
        .order_by(Sector.display_order)
        .all()
    )

    data = [
        SectorRead.model_validate(sector).model_dump()
        for sector in sectors
    ]

    return success_response(
        message="Sectors retrieved successfully",
        data=data,
    )


@router.get("/sectors/{sector_id}")
def get_sector(sector_id: int, db: Session = Depends(get_db)):
    sector = db.get(Sector, sector_id)

    if sector is None:
        return not_found_response(
            message="Sector not found",
            error_code="SECTOR_NOT_FOUND",
        )

    data = SectorRead.model_validate(sector).model_dump()

    return success_response(
        message="Sector retrieved successfully",
        data=data,
    )


@router.post("/sectors", status_code=status.HTTP_201_CREATED)
def create_sector(payload: SectorCreate, db: Session = Depends(get_db)):
    existing_name = (
        db.query(Sector)
        .filter(Sector.sector_name == payload.sector_name)
        .first()
    )

    if existing_name is not None:
        return conflict_response(
            message="Sector name already exists",
            error_code="SECTOR_NAME_EXISTS",
        )

    existing_order = (
        db.query(Sector)
        .filter(Sector.display_order == payload.display_order)
        .first()
    )

    if existing_order is not None:
        return conflict_response(
            message="Display order already exists",
            error_code="DISPLAY_ORDER_EXISTS",
        )

    sector = Sector(
        sector_name=payload.sector_name,
        company_count=payload.company_count,
        source_name=payload.source_name,
        display_order=payload.display_order,
    )

    db.add(sector)
    db.commit()
    db.refresh(sector)

    data = SectorRead.model_validate(sector).model_dump()

    return success_response(
        message="Sector created successfully",
        data=data,
    )


@router.patch("/sectors/{sector_id}")
def update_sector(
    sector_id: int,
    payload: SectorUpdate,
    db: Session = Depends(get_db),
):
    sector = db.get(Sector, sector_id)

    if sector is None:
        return not_found_response(
            message="Sector not found",
            error_code="SECTOR_NOT_FOUND",
        )

    update_data = payload.model_dump(exclude_unset=True)

    if "sector_name" in update_data:
        existing_name = (
            db.query(Sector)
            .filter(
                Sector.sector_name == update_data["sector_name"],
                Sector.sector_id != sector_id,
            )
            .first()
        )

        if existing_name is not None:
            return conflict_response(
                message="Sector name already exists",
                error_code="SECTOR_NAME_EXISTS",
            )

        sector.sector_name = update_data["sector_name"]

    if "company_count" in update_data:
        sector.company_count = update_data["company_count"]

    if "source_name" in update_data:
        sector.source_name = update_data["source_name"]

    if "display_order" in update_data:
        existing_order = (
            db.query(Sector)
            .filter(
                Sector.display_order == update_data["display_order"],
                Sector.sector_id != sector_id,
            )
            .first()
        )

        if existing_order is not None:
            return conflict_response(
                message="Display order already exists",
                error_code="DISPLAY_ORDER_EXISTS",
            )

        sector.display_order = update_data["display_order"]

    db.commit()
    db.refresh(sector)

    data = SectorRead.model_validate(sector).model_dump()

    return success_response(
        message="Sector updated successfully",
        data=data,
    )


# ============================================================
# Events Management Admin API
# ============================================================


@router.get("/events")
def list_events(
    event_date: Optional[DateType] = Query(default=None),
    zone_id: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
):
    query = db.query(LiveEvent)

    if event_date is not None:
        query = query.filter(LiveEvent.event_date == event_date)

    if zone_id is not None:
        query = query.filter(LiveEvent.zone_id == zone_id)

    if status_filter is not None:
        query = query.filter(LiveEvent.event_status == status_filter)

    events = (
        query
        .order_by(LiveEvent.event_date, LiveEvent.event_time_start)
        .all()
    )

    data = [
        EventRead.model_validate(event).model_dump()
        for event in events
    ]

    return success_response(
        message="Events retrieved successfully",
        data=data,
    )


@router.get("/events/{event_id}")
def get_event(event_id: int, db: Session = Depends(get_db)):
    event = db.get(LiveEvent, event_id)

    if event is None:
        return not_found_response(
            message="Event not found",
            error_code="EVENT_NOT_FOUND",
        )

    data = EventRead.model_validate(event).model_dump()

    return success_response(
        message="Event retrieved successfully",
        data=data,
    )


@router.post("/events", status_code=status.HTTP_201_CREATED)
def create_event(payload: EventCreate, db: Session = Depends(get_db)):
    zone_error = validate_bookable_open_zone(payload.zone_id, db)

    if zone_error is not None:
        return zone_error

    event = Event(
        zone_id=payload.zone_id,
        event_name=payload.event_name,
        event_date=payload.event_date,
        event_time_start=payload.event_time_start,
        event_time_end=payload.event_time_end,
        event_location=payload.event_location,
        event_organizer=payload.event_organizer,
        event_attendee_count=payload.event_attendee_count,
    )

    db.add(event)

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()

        if is_overlap_error(exc):
            return conflict_response(
                message="This event overlaps another event or booking in the selected zone",
                error_code="EVENT_OVERLAP",
            )

        raise

    db.refresh(event)

    live_event = db.get(LiveEvent, event.event_id)
    data = EventRead.model_validate(live_event).model_dump()

    return success_response(
        message="Event created successfully",
        data=data,
    )


@router.patch("/events/{event_id}")
def update_event(
    event_id: int,
    payload: EventUpdate,
    db: Session = Depends(get_db),
):
    event = db.get(Event, event_id)

    if event is None:
        return not_found_response(
            message="Event not found",
            error_code="EVENT_NOT_FOUND",
        )

    update_data = payload.model_dump(exclude_unset=True)

    target_zone_id = update_data.get("zone_id", event.zone_id)
    zone_error = validate_bookable_open_zone(target_zone_id, db)

    if zone_error is not None:
        return zone_error

    target_start = update_data.get("event_time_start", event.event_time_start)
    target_end = update_data.get("event_time_end", event.event_time_end)

    if target_end <= target_start:
        return bad_request_response(
            message="event_time_end must be after event_time_start",
            error_code="INVALID_TIME_RANGE",
        )

    if "zone_id" in update_data:
        event.zone_id = update_data["zone_id"]

    if "event_name" in update_data:
        event.event_name = update_data["event_name"]

    if "event_date" in update_data:
        event.event_date = update_data["event_date"]

    if "event_time_start" in update_data:
        event.event_time_start = update_data["event_time_start"]

    if "event_time_end" in update_data:
        event.event_time_end = update_data["event_time_end"]

    if "event_location" in update_data:
        event.event_location = update_data["event_location"]

    if "event_organizer" in update_data:
        event.event_organizer = update_data["event_organizer"]

    if "event_attendee_count" in update_data:
        event.event_attendee_count = update_data["event_attendee_count"]

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()

        if is_overlap_error(exc):
            return conflict_response(
                message="This event overlaps another event or booking in the selected zone",
                error_code="EVENT_OVERLAP",
            )

        raise

    db.refresh(event)

    live_event = db.get(LiveEvent, event.event_id)
    data = EventRead.model_validate(live_event).model_dump()

    return success_response(
        message="Event updated successfully",
        data=data,
    )


# ============================================================
# Booking Management Admin API
# ============================================================


@router.get("/bookings")
def list_bookings(
    booking_date: Optional[DateType] = Query(default=None),
    zone_id: Optional[str] = Query(default=None),
    booking_type: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
):
    query = db.query(LiveBooking)

    if booking_date is not None:
        query = query.filter(LiveBooking.booking_date == booking_date)

    if zone_id is not None:
        query = query.filter(LiveBooking.zone_id == zone_id)

    if booking_type is not None:
        query = query.filter(LiveBooking.booking_type == booking_type)

    if status_filter is not None:
        query = query.filter(LiveBooking.booking_status == status_filter)

    bookings = (
        query
        .order_by(LiveBooking.booking_date, LiveBooking.booking_time_start)
        .all()
    )

    data = [
        BookingRead.model_validate(booking).model_dump()
        for booking in bookings
    ]

    return success_response(
        message="Bookings retrieved successfully",
        data=data,
    )


@router.get("/bookings/{booking_id}")
def get_booking(booking_id: int, db: Session = Depends(get_db)):
    booking = db.get(LiveBooking, booking_id)

    if booking is None:
        return not_found_response(
            message="Booking not found",
            error_code="BOOKING_NOT_FOUND",
        )

    data = BookingRead.model_validate(booking).model_dump()

    return success_response(
        message="Booking retrieved successfully",
        data=data,
    )


@router.post("/bookings", status_code=status.HTTP_201_CREATED)
def create_booking(payload: BookingCreate, db: Session = Depends(get_db)):
    zone_error = validate_bookable_open_zone(payload.zone_id, db)

    if zone_error is not None:
        return zone_error

    booking = Booking(
        zone_id=payload.zone_id,
        booking_type=payload.booking_type,
        booking_name=payload.booking_name,
        visitor_name=payload.visitor_name,
        visitor_phone=payload.visitor_phone,
        visitor_is_client=payload.visitor_is_client,
        booking_start_date=payload.booking_start_date,
        booking_end_date=payload.booking_end_date,
        booking_date=payload.booking_date,
        booking_time_start=payload.booking_time_start,
        booking_time_end=payload.booking_time_end,
    )

    db.add(booking)

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()

        if is_overlap_error(exc):
            return conflict_response(
                message="This booking overlaps another booking or event in the selected zone",
                error_code="BOOKING_OVERLAP",
            )

        raise

    db.refresh(booking)

    live_booking = db.get(LiveBooking, booking.booking_id)
    data = BookingRead.model_validate(live_booking).model_dump()

    return success_response(
        message="Booking created successfully",
        data=data,
    )


@router.patch("/bookings/{booking_id}")
def update_booking(
    booking_id: int,
    payload: BookingUpdate,
    db: Session = Depends(get_db),
):
    booking = db.get(Booking, booking_id)

    if booking is None:
        return not_found_response(
            message="Booking not found",
            error_code="BOOKING_NOT_FOUND",
        )

    update_data = payload.model_dump(exclude_unset=True)

    target_zone_id = update_data.get("zone_id", booking.zone_id)
    zone_error = validate_bookable_open_zone(target_zone_id, db)

    if zone_error is not None:
        return zone_error

    target_start = update_data.get("booking_time_start", booking.booking_time_start)
    target_end = update_data.get("booking_time_end", booking.booking_time_end)
    target_start_date = update_data.get("booking_start_date", booking.booking_start_date)
    target_end_date = update_data.get("booking_end_date", booking.booking_end_date)

    if target_end_date < target_start_date:
        return bad_request_response(
            message="booking_end_date must be on or after booking_start_date",
            error_code="INVALID_DATE_RANGE",
        )

    if target_end <= target_start:
        return bad_request_response(
            message="booking_time_end must be after booking_time_start",
            error_code="INVALID_TIME_RANGE",
        )

    if "zone_id" in update_data:
        booking.zone_id = update_data["zone_id"]

    if "booking_type" in update_data:
        booking.booking_type = update_data["booking_type"]

    if "booking_name" in update_data:
        booking.booking_name = update_data["booking_name"]

    if "visitor_name" in update_data:
        booking.visitor_name = update_data["visitor_name"]

    if "visitor_phone" in update_data:
        booking.visitor_phone = update_data["visitor_phone"]

    if "visitor_is_client" in update_data:
        booking.visitor_is_client = update_data["visitor_is_client"]

    if "booking_start_date" in update_data:
        booking.booking_start_date = update_data["booking_start_date"]

    if "booking_end_date" in update_data:
        booking.booking_end_date = update_data["booking_end_date"]

    if "booking_date" in update_data:
        booking.booking_date = update_data["booking_date"]
    elif "booking_start_date" in update_data:
        booking.booking_date = update_data["booking_start_date"]

    if "booking_time_start" in update_data:
        booking.booking_time_start = update_data["booking_time_start"]

    if "booking_time_end" in update_data:
        booking.booking_time_end = update_data["booking_time_end"]

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()

        if is_overlap_error(exc):
            return conflict_response(
                message="This booking overlaps another booking or event in the selected zone",
                error_code="BOOKING_OVERLAP",
            )

        raise

    db.refresh(booking)

    live_booking = db.get(LiveBooking, booking.booking_id)
    data = BookingRead.model_validate(live_booking).model_dump()

    return success_response(
        message="Booking updated successfully",
        data=data,
    )


# ============================================================
# Live Activity Admin API
# Read-only endpoints.
# ============================================================


@router.get("/live-activity/metrics")
def get_live_activity_metrics(db: Session = Depends(get_db)):
    metrics = db.query(LiveActivityMetric).first()

    if metrics is None:
        return not_found_response(
            message="Live activity metrics not found",
            error_code="LIVE_ACTIVITY_METRICS_NOT_FOUND",
        )

    data = LiveActivityMetricRead.model_validate(metrics).model_dump()

    return success_response(
        message="Live activity metrics retrieved successfully",
        data=data,
    )


@router.get("/live-activity/feed")
def list_live_activity_feed(
    limit: int = Query(default=20, ge=1, le=100),
    category: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(LiveActivityFeed)

    if category is not None:
        query = query.filter(LiveActivityFeed.category == category)

    feed_items = (
        query
        .order_by(LiveActivityFeed.occurred_at.desc())
        .limit(limit)
        .all()
    )

    data = [
        LiveActivityFeedRead.model_validate(item).model_dump()
        for item in feed_items
    ]

    return success_response(
        message="Live activity feed retrieved successfully",
        data=data,
    )

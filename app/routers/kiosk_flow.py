from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.kiosk_flow_schemas import (
    CreateFaceProfileRequest,
    CreateProfileRequest,
    EventSelectionCreate,
    FacialConsentRequest,
    KioskBookingCreate,
    KioskBookingRead,
    KioskEventRead,
    KioskPackageRead,
    KioskVisitorRead,
    OtherAssistanceCreate,
    ProfileLookupRequest,
    RecognizeFaceRequest,
    RecognizeFaceResponse,
    VisitSessionCreate,
    VisitSessionRead,
)
from app.kiosk_flow_services import (
    calculate_end_time,
    create_activity,
    find_previous_visit,
    normalize_name,
    normalize_phone,
    service_to_booking_defaults,
)
from app.models import (
    Booking,
    Event,
    FaceProfile,
    OtherAssistanceRequest,
    Package,
    VisitSession,
    Visitor,
)


router = APIRouter(prefix="/api/kiosk", tags=["Kiosk Flow"])


def success_response(
    message: str = "Request completed successfully",
    data: Any = None,
) -> dict[str, Any]:
    return {
        "success": True,
        "message": message,
        "data": {} if data is None else jsonable_encoder(data),
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
        content=error_response(message=message, error_code=error_code),
    )


def bad_request_response(message: str, error_code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=error_response(message=message, error_code=error_code),
    )


def conflict_response(message: str, error_code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=error_response(message=message, error_code=error_code),
    )


def find_visitor_by_phone(db: Session, mobile_number: str) -> Visitor | None:
    wanted_phone = normalize_phone(mobile_number)
    for visitor in db.query(Visitor).all():
        if normalize_phone(visitor.visitor_phone) == wanted_phone:
            return visitor
    return None


def find_visitor_by_profile(db: Session, payload: ProfileLookupRequest) -> Visitor | None:
    wanted_name = normalize_name(payload.full_name)
    visitor = find_visitor_by_phone(db, payload.mobile_number)

    if visitor is None:
        return None

    if normalize_name(visitor.visitor_name) == wanted_name:
        return visitor

    return None


def visitor_payload(visitor: Visitor) -> dict[str, Any]:
    return KioskVisitorRead.model_validate(visitor).model_dump(mode="json")


def current_database_date(db: Session) -> date:
    try:
        return db.query(func.current_date()).scalar()
    except AttributeError:
        return date.today()


def event_payload(event: Event) -> dict[str, Any]:
    organizer = getattr(event, "event_organizer", None) or "Innovation City"
    data = KioskEventRead(
        event_id=event.event_id,
        event_name=event.event_name,
        event_date=event.event_date,
        event_time_start=event.event_time_start,
        event_time_end=event.event_time_end,
        event_location=event.event_location,
        short_description=f"Hosted by {organizer}",
    )
    return data.model_dump(mode="json")


@router.post("/recognize-face")
def recognize_face(
    payload: RecognizeFaceRequest,
    db: Session = Depends(get_db),
):
    visitor = None
    if payload.simulate_mobile_number:
        visitor = find_visitor_by_phone(db, payload.simulate_mobile_number)

    data = RecognizeFaceResponse(
        recognized=visitor is not None,
        visitor_id=visitor.visitor_id if visitor else None,
    )
    return success_response(
        message="Face recognition placeholder completed",
        data=data.model_dump(),
    )


@router.post("/profile-lookup")
def profile_lookup(
    payload: ProfileLookupRequest,
    db: Session = Depends(get_db),
):
    visitor = find_visitor_by_profile(db, payload)

    if visitor is None:
        return not_found_response(
            message="Visitor profile not found",
            error_code="VISITOR_NOT_FOUND",
        )

    return success_response(
        message="Visitor profile found",
        data=visitor_payload(visitor),
    )


@router.post("/profiles", status_code=status.HTTP_201_CREATED)
def create_profile(
    payload: CreateProfileRequest,
    db: Session = Depends(get_db),
):
    existing = find_visitor_by_phone(db, payload.mobile_number)

    if existing is not None:
        return conflict_response(
            message="A visitor with this mobile number already exists",
            error_code="VISITOR_PHONE_EXISTS",
        )

    visitor = Visitor(
        visitor_name=payload.full_name,
        visitor_phone=normalize_phone(payload.mobile_number),
        visitor_email=payload.email,
        visitor_type=payload.visitor_type,
        license_number=payload.license_number,
        company_name=payload.company_name,
        company_number=payload.company_number,
        is_existing_client=payload.visitor_type == "client",
        lead_source="screen_2_check_in",
    )
    db.add(visitor)
    db.commit()
    db.refresh(visitor)

    return success_response(
        message="Visitor profile created",
        data=visitor_payload(visitor),
    )


@router.post("/facial-consent")
def save_facial_consent(
    payload: FacialConsentRequest,
    db: Session = Depends(get_db),
):
    visitor = db.get(Visitor, payload.visitor_id)

    if visitor is None:
        return not_found_response(
            message="Visitor not found",
            error_code="VISITOR_NOT_FOUND",
        )

    visitor.face_consent_given = payload.consent_given
    visitor.face_consent_at = func.current_timestamp() if payload.consent_given else None
    db.commit()
    db.refresh(visitor)

    return success_response(
        message="Facial consent saved",
        data=visitor_payload(visitor),
    )


@router.post("/face-profile", status_code=status.HTTP_201_CREATED)
def create_face_profile(
    payload: CreateFaceProfileRequest,
    db: Session = Depends(get_db),
):
    visitor = db.get(Visitor, payload.visitor_id)

    if visitor is None:
        return not_found_response(
            message="Visitor not found",
            error_code="VISITOR_NOT_FOUND",
        )

    if not visitor.face_consent_given:
        return bad_request_response(
            message="Facial consent is required before creating a face profile",
            error_code="FACIAL_CONSENT_REQUIRED",
        )

    identifier = f"placeholder-face-{visitor.visitor_id}"
    existing = (
        db.query(FaceProfile)
        .filter(FaceProfile.face_identifier == identifier)
        .first()
    )

    if existing is None:
        existing = FaceProfile(
            visitor_id=visitor.visitor_id,
            face_identifier=identifier,
            consent_given=True,
        )
        db.add(existing)
        visitor.face_reference_id = identifier
        db.commit()
        db.refresh(existing)
        db.refresh(visitor)

    return success_response(
        message="Placeholder face profile created",
        data={
            "face_profile_id": existing.face_profile_id,
            "visitor_id": existing.visitor_id,
            "face_identifier": existing.face_identifier,
        },
    )


@router.get("/visitors/{visitor_id}")
def get_visitor(
    visitor_id: int,
    db: Session = Depends(get_db),
):
    visitor = db.get(Visitor, visitor_id)

    if visitor is None:
        return not_found_response(
            message="Visitor not found",
            error_code="VISITOR_NOT_FOUND",
        )

    return success_response(
        message="Visitor retrieved",
        data=visitor_payload(visitor),
    )


@router.get("/current-booking")
def get_current_booking(
    visitor_id: int | None = Query(default=None),
    mobile_number: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    current_date = current_database_date(db)
    query = db.query(Booking).filter(Booking.booking_date == current_date)

    if visitor_id is not None:
        query = query.filter(Booking.visitor_id == visitor_id)
    elif mobile_number:
        query = query.filter(Booking.visitor_phone == normalize_phone(mobile_number))
    else:
        return bad_request_response(
            message="visitor_id or mobile_number is required",
            error_code="BOOKING_LOOKUP_REQUIRED",
        )

    booking = query.order_by(Booking.booking_time_start).first()

    if booking is None:
        return not_found_response(
            message="Current booking not found",
            error_code="BOOKING_NOT_FOUND",
        )

    data = KioskBookingRead(
        booking_id=booking.booking_id,
        booking_type=booking.booking_type,
        booking_name=booking.booking_name,
        booking_date=booking.booking_date,
        booking_time_start=booking.booking_time_start,
        booking_time_end=booking.booking_time_end,
        zone_id=booking.zone_id,
        room_name=booking.booking_name,
    )
    return success_response(
        message="Current booking retrieved",
        data=data.model_dump(mode="json"),
    )


@router.post("/visit-sessions", status_code=status.HTTP_201_CREATED)
def create_visit_session(
    payload: VisitSessionCreate,
    db: Session = Depends(get_db),
):
    previous_visit = (
        find_previous_visit(db, payload.visitor_id)
        if payload.visitor_id is not None
        else None
    )
    session = VisitSession(
        visitor_id=payload.visitor_id,
        recognition_method=payload.recognition_method,
        is_returning_visitor=previous_visit is not None,
        previous_visit_id=previous_visit.visit_session_id if previous_visit else None,
        current_selected_service=payload.current_selected_service,
        visit_purpose=payload.visit_purpose,
        notes=payload.notes,
    )
    db.add(session)

    if payload.visitor_id is not None:
        visitor = db.get(Visitor, payload.visitor_id)
        if visitor is not None:
            visitor.last_visit_at = func.current_timestamp()

    db.commit()
    db.refresh(session)

    return success_response(
        message="Visit session created",
        data=VisitSessionRead.model_validate(session).model_dump(mode="json"),
    )


@router.post("/bookings", status_code=status.HTTP_201_CREATED)
def create_kiosk_booking(
    payload: KioskBookingCreate,
    db: Session = Depends(get_db),
):
    visitor = db.get(Visitor, payload.visitor_id)

    if visitor is None:
        return not_found_response(
            message="Visitor not found",
            error_code="VISITOR_NOT_FOUND",
        )

    booking_type, zone_id, default_room_name = service_to_booking_defaults(payload.service_type)
    room_name = payload.room_name or default_room_name
    end_time = calculate_end_time(payload.booking_time_start, payload.duration_minutes)
    booking = Booking(
        visitor_id=visitor.visitor_id,
        zone_id=zone_id,
        booking_type=booking_type,
        booking_name=room_name,
        visitor_name=visitor.visitor_name,
        visitor_phone=visitor.visitor_phone,
        visitor_email=visitor.visitor_email,
        visitor_is_client=visitor.visitor_type == "client",
        booking_start_date=payload.booking_date,
        booking_end_date=payload.booking_date,
        booking_date=payload.booking_date,
        booking_time_start=payload.booking_time_start,
        booking_time_end=end_time,
    )
    db.add(booking)

    session = (
        db.get(VisitSession, payload.visit_session_id)
        if payload.visit_session_id is not None
        else None
    )
    if session is not None:
        session.current_selected_service = payload.service_type

    create_activity(
        db,
        visitor_id=visitor.visitor_id,
        visit_session_id=payload.visit_session_id,
        selected_service=payload.service_type,
        visit_purpose=room_name,
        notes="Created from kiosk",
    )
    db.commit()
    db.refresh(booking)

    data = KioskBookingRead(
        booking_id=booking.booking_id,
        booking_type=booking.booking_type,
        booking_name=booking.booking_name,
        booking_date=booking.booking_date,
        booking_time_start=booking.booking_time_start,
        booking_time_end=booking.booking_time_end,
        zone_id=booking.zone_id,
        room_name=room_name,
    )
    return success_response(
        message="Booking created",
        data=data.model_dump(mode="json"),
    )


@router.get("/events/today")
def list_today_events(db: Session = Depends(get_db)):
    current_date = current_database_date(db)
    events = (
        db.query(Event)
        .filter(Event.event_date == current_date)
        .order_by(Event.event_time_start)
        .all()
    )

    return success_response(
        message="Today's events retrieved",
        data=[event_payload(event) for event in events],
    )


@router.post("/events/select")
def select_event(
    payload: EventSelectionCreate,
    db: Session = Depends(get_db),
):
    visitor = db.get(Visitor, payload.visitor_id)
    event = db.get(Event, payload.event_id)

    if visitor is None:
        return not_found_response(
            message="Visitor not found",
            error_code="VISITOR_NOT_FOUND",
        )

    if event is None:
        return not_found_response(
            message="Event not found",
            error_code="EVENT_NOT_FOUND",
        )

    session = (
        db.get(VisitSession, payload.visit_session_id)
        if payload.visit_session_id is not None
        else None
    )
    if session is not None:
        session.current_selected_service = "event"
        session.visit_purpose = event.event_name

    create_activity(
        db,
        visitor_id=visitor.visitor_id,
        visit_session_id=payload.visit_session_id,
        selected_service="event",
        visit_purpose=event.event_name,
        notes=f"Selected event #{event.event_id}",
    )
    db.commit()

    return success_response(
        message="Event selected",
        data=event_payload(event),
    )


@router.get("/packages")
def list_packages(db: Session = Depends(get_db)):
    packages = (
        db.query(Package)
        .filter(Package.is_active.is_(True))
        .order_by(Package.package_id)
        .all()
    )
    data = [
        KioskPackageRead.model_validate(package).model_dump(mode="json")
        for package in packages
    ]

    return success_response(
        message="Packages retrieved",
        data=data,
    )


@router.post("/other-assistance", status_code=status.HTTP_201_CREATED)
def create_other_assistance(
    payload: OtherAssistanceCreate,
    db: Session = Depends(get_db),
):
    visitor = db.get(Visitor, payload.visitor_id)

    if visitor is None:
        return not_found_response(
            message="Visitor not found",
            error_code="VISITOR_NOT_FOUND",
        )

    request = OtherAssistanceRequest(
        visitor_id=visitor.visitor_id,
        visit_session_id=payload.visit_session_id,
        reason=payload.reason,
        notes=payload.notes,
    )
    db.add(request)

    session = (
        db.get(VisitSession, payload.visit_session_id)
        if payload.visit_session_id is not None
        else None
    )
    if session is not None:
        session.current_selected_service = "other"
        session.visit_purpose = payload.reason

    create_activity(
        db,
        visitor_id=visitor.visitor_id,
        visit_session_id=payload.visit_session_id,
        selected_service="other",
        visit_purpose=payload.reason,
        notes=payload.notes,
    )
    db.commit()
    db.refresh(request)

    return success_response(
        message="Other assistance request created",
        data={
            "other_assistance_request_id": request.other_assistance_request_id,
            "visitor_id": request.visitor_id,
            "visit_session_id": request.visit_session_id,
            "reason": request.reason,
            "notes": request.notes,
        },
    )

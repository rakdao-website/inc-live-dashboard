from datetime import date, datetime, time
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.face_recognition_service import FaceRecognitionUnavailable, get_face_recognition_service
from app.kiosk_flow_schemas import (
    CreateFaceProfileRequest,
    CreateProfileRequest,
    EventSelectionCreate,
    FacialConsentRequest,
    KioskBookingCreate,
    KioskBookingRead,
    KioskEventRead,
    KioskVisitorRead,
    LicenseLookupRequest,
    OtherAssistanceCreate,
    ProfileLookupRequest,
    RecognizeFaceRequest,
    RecognizeFaceResponse,
    RoomQuestionRequest,
    RoomQuestionResponse,
    SpeakRequest,
    ParseTranscriptRequest,
    VisitSessionCreate,
    VisitSessionRead,
)
from app.room_question_service import answer_room_question
from app.voice_agent.tts_service import TtsUnavailable, synthesize_speech
from app.booking_intent_service import parse_booking_intent
from app.registration_intent_service import parse_visitor_intent
from app.kiosk_flow_services import (
    calculate_end_time,
    create_activity,
    find_previous_visit,
    normalize_name,
    normalize_phone,
    schedule_has_conflict,
    service_to_booking_defaults,
)
from app.models import (
    Booking,
    Event,
    FaceProfile,
    OtherAssistanceRequest,
    VisitSession,
    VisitorActivity,
    VisitorCheckIn,
    Visitor,
    Zone,
)
from app.operating_hours import OPERATING_HOURS_MESSAGE, is_within_operating_hours


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


def is_overlap_error(exc: SQLAlchemyError) -> bool:
    error_text = str(exc).lower()
    return "overlaps" in error_text or "overlap" in error_text


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


def find_visitor_by_license(db: Session, license_number: str) -> Visitor | None:
    wanted_license = str(license_number or "").strip().lower()
    for visitor in db.query(Visitor).all():
        if str(visitor.license_number or "").strip().lower() == wanted_license:
            return visitor
    return None


def find_visitor_by_face_name(db: Session, name: str | None) -> Visitor | None:
    wanted_face_identifier = str(name or "").strip()
    wanted_name = normalize_name(wanted_face_identifier)
    if not wanted_name and not wanted_face_identifier:
        return None

    for visitor in db.query(Visitor).all():
        if str(getattr(visitor, "face_reference_id", "") or "").strip() == wanted_face_identifier:
            return visitor
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


def current_database_time(db: Session) -> time:
    try:
        value = db.query(func.current_time()).scalar()
    except AttributeError:
        return datetime.now().time().replace(microsecond=0)

    if isinstance(value, time):
        return value.replace(tzinfo=None, microsecond=0)
    if isinstance(value, str):
        try:
            return time.fromisoformat(value.split(".")[0])
        except ValueError:
            pass
    return datetime.now().time().replace(microsecond=0)


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
    matched_name = None
    confidence = None

    if payload.simulate_mobile_number:
        visitor = find_visitor_by_phone(db, payload.simulate_mobile_number)
    else:
        if not payload.images_base64 and not payload.image_base64:
            return bad_request_response(
                message="A browser camera image is required for face recognition.",
                error_code="FACE_IMAGE_REQUIRED",
            )

        try:
            recognizer = get_face_recognition_service()
            match = (
                recognizer.recognize_images_base64(payload.images_base64)
                if payload.images_base64
                else recognizer.recognize_image_base64(payload.image_base64)
                if payload.image_base64
                else None
            )
        except FaceRecognitionUnavailable as exc:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content=error_response(
                    message=str(exc),
                    error_code="FACE_RECOGNITION_UNAVAILABLE",
                ),
            )
        except ValueError as exc:
            return bad_request_response(
                message=str(exc),
                error_code="FACE_IMAGE_INVALID",
            )
        except Exception:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content=error_response(
                    message="Face recognition failed. Please try again or use manual details.",
                    error_code="FACE_RECOGNITION_FAILED",
                ),
            )

        matched_name = match.name
        confidence = match.score
        if match.recognized:
            visitor = find_visitor_by_face_name(db, match.name)

    data = RecognizeFaceResponse(
        recognized=visitor is not None,
        visitor_id=visitor.visitor_id if visitor else None,
        matched_name=matched_name,
        confidence=confidence,
    )
    return success_response(
        message="Face recognition completed",
        data=data.model_dump(),
    )


@router.post("/room-question")
async def room_question(
    payload: RoomQuestionRequest,
    db: Session = Depends(get_db),
):
    answer, source = await answer_room_question(db, payload.question)
    return success_response(
        message="Room question answered",
        data=RoomQuestionResponse(answer=answer, source=source).model_dump(),
    )


@router.post("/speak")
async def speak(payload: SpeakRequest):
    """
    Returns raw MP3 bytes (not the usual JSON envelope, since this is audio).
    A non-200 here is expected and harmless when TTS isn't configured - the
    frontend catches it and falls back to the browser's own speech synthesis.
    """
    try:
        audio_bytes, content_type = await synthesize_speech(payload.text)
    except TtsUnavailable as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=error_response(str(exc), "TTS_UNAVAILABLE"),
        )
    return Response(content=audio_bytes, media_type=content_type)


@router.post("/parse-booking-intent")
async def parse_booking_intent_route(payload: ParseTranscriptRequest, db: Session = Depends(get_db)):
    result = await parse_booking_intent(db, payload.transcript, service_type=payload.service_type)
    return success_response(message="Booking intent parsed", data=result.to_dict())


@router.post("/parse-registration-intent")
async def parse_registration_intent_route(payload: ParseTranscriptRequest):
    result = await parse_visitor_intent(payload.transcript)
    return success_response(message="Registration intent parsed", data=result.to_dict())


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


@router.post("/license-lookup")
def license_lookup(
    payload: LicenseLookupRequest,
    db: Session = Depends(get_db),
):
    visitor = find_visitor_by_license(db, payload.license_number)

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
        license_number=None,
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

    identifier = f"visitor:{visitor.visitor_id}"
    try:
        sample_count = get_face_recognition_service().enroll_images(
            identifier,
            payload.images_base64,
        )
    except FaceRecognitionUnavailable as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=error_response(
                message=str(exc),
                error_code="FACE_RECOGNITION_UNAVAILABLE",
            ),
        )
    except ValueError as exc:
        return bad_request_response(
            message=str(exc),
            error_code="FACE_ENROLLMENT_FAILED",
        )
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response(
                message="Face enrollment failed. Please retry the scan.",
                error_code="FACE_ENROLLMENT_FAILED",
            ),
        )

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
        message="Face profile enrolled",
        data={
            "face_profile_id": existing.face_profile_id,
            "visitor_id": existing.visitor_id,
            "face_identifier": existing.face_identifier,
            "sample_count": sample_count,
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
    response = get_current_bookings(visitor_id=visitor_id, mobile_number=mobile_number, db=db)
    if not isinstance(response, dict):
        return response
    bookings = response["data"]
    if not bookings:
        return not_found_response(
            message="Current booking not found",
            error_code="BOOKING_NOT_FOUND",
        )
    return success_response(
        message="Current booking retrieved",
        data=bookings[0],
    )


@router.get("/current-bookings")
def get_current_bookings(
    visitor_id: int | None = Query(default=None),
    mobile_number: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    current_date = current_database_date(db)
    current_time = current_database_time(db)
    query = db.query(Booking).filter(
        Booking.booking_date == current_date,
        Booking.booking_time_end > current_time,
    )

    if visitor_id is not None:
        query = query.filter(Booking.visitor_id == visitor_id)
    elif mobile_number:
        query = query.filter(Booking.visitor_phone == normalize_phone(mobile_number))
    else:
        return bad_request_response(
            message="visitor_id or mobile_number is required",
            error_code="BOOKING_LOOKUP_REQUIRED",
        )

    bookings = query.order_by(Booking.booking_time_start).all()

    if not bookings:
        return not_found_response(
            message="Current booking not found",
            error_code="BOOKING_NOT_FOUND",
        )

    data = []
    for booking in bookings:
        if booking.booking_time_end <= current_time:
            continue
        room_name = getattr(getattr(booking, "zone", None), "zone_name", None) or booking.booking_name
        data.append(
            KioskBookingRead(
                booking_id=booking.booking_id,
                booking_type=booking.booking_type,
                booking_name=booking.booking_name,
                booking_date=booking.booking_date,
                booking_time_start=booking.booking_time_start,
                booking_time_end=booking.booking_time_end,
                zone_id=booking.zone_id,
                room_name=room_name,
            ).model_dump(mode="json")
        )

    if not data:
        return not_found_response(
            message="Current booking not found",
            error_code="BOOKING_NOT_FOUND",
        )

    return success_response(
        message="Current bookings retrieved",
        data=data,
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

    if payload.visitor_id is not None and previous_visit is not None:
        previous_activity = (
            db.query(VisitorActivity)
            .filter(VisitorActivity.visitor_id == payload.visitor_id)
            .order_by(VisitorActivity.created_at.desc(), VisitorActivity.visitor_activity_id.desc())
            .first()
        )
        previous_details = "No previous visit details were captured."
        if previous_activity is not None:
            previous_bits = [
                previous_activity.visit_purpose,
                previous_activity.notes,
            ]
            previous_details = " ".join(bit for bit in previous_bits if bit) or previous_details
        create_activity(
            db,
            visitor_id=payload.visitor_id,
            visit_session_id=session.visit_session_id,
            selected_service="returning_visit",
            visit_purpose=previous_activity.visit_purpose if previous_activity else None,
            notes=f"Returning visitor is back. Last visit: {previous_details}",
        )
        db.commit()

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

    booking_type, default_zone_id, default_room_name = service_to_booking_defaults(payload.service_type)
    zone_id = payload.zone_id or default_zone_id
    zone = db.get(Zone, zone_id)

    if zone is None:
        return not_found_response(
            message="Room not found",
            error_code="ZONE_NOT_FOUND",
        )

    if not zone.is_bookable:
        return bad_request_response(
            message="Room is not bookable",
            error_code="ZONE_NOT_BOOKABLE",
        )

    if zone.is_closed:
        return bad_request_response(
            message="Room is currently closed",
            error_code="ZONE_CLOSED",
        )

    if payload.service_type == "meeting_room" and zone.zone_type != "meeting_room":
        return bad_request_response(
            message="Please choose a meeting room",
            error_code="INVALID_ROOM_TYPE",
        )

    if payload.service_type in ("podcast_studio", "tiktok_studio") and zone_id != default_zone_id:
        return bad_request_response(
            message="This studio has a fixed room",
            error_code="INVALID_ROOM_TYPE",
        )

    room_name = payload.room_name or zone.zone_name or default_room_name
    end_time = calculate_end_time(payload.booking_time_start, payload.duration_minutes)

    if end_time <= payload.booking_time_start:
        return bad_request_response(
            message="Please choose a time and duration that ends before midnight.",
            error_code="BOOKING_ENDS_AFTER_MIDNIGHT",
        )

    if not is_within_operating_hours(payload.booking_time_start, end_time):
        return bad_request_response(
            message=OPERATING_HOURS_MESSAGE,
            error_code="OUTSIDE_OPERATING_HOURS",
        )

    if schedule_has_conflict(
        db,
        zone_id=zone_id,
        schedule_date=payload.booking_date,
        start_time=payload.booking_time_start,
        end_time=end_time,
    ):
        return conflict_response(
            message="This time slot is already booked. Please choose another time.",
            error_code="BOOKING_OVERLAP",
        )

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
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()

        if is_overlap_error(exc):
            return conflict_response(
                message="This time slot is already booked. Please choose another time.",
                error_code="BOOKING_OVERLAP",
            )

        raise

    db.refresh(booking)

    data = KioskBookingRead(
        booking_id=booking.booking_id,
        booking_type=booking.booking_type,
        booking_name=booking.booking_name,
        booking_date=booking.booking_date,
        booking_time_start=booking.booking_time_start,
        booking_time_end=booking.booking_time_end,
        zone_id=booking.zone_id,
        room_name=zone.zone_name or room_name,
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


def event_selection_matches_activity(
    activity: VisitorActivity,
    *,
    visitor_id: int,
    visit_session_id: int | None,
    event_name: str,
) -> bool:
    return (
        activity.visitor_id == visitor_id
        and activity.visit_session_id == visit_session_id
        and activity.selected_service == "event"
        and activity.visit_purpose == event_name
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

    existing_activity = (
        db.query(VisitorActivity)
        .filter(
            VisitorActivity.visitor_id == visitor.visitor_id,
            VisitorActivity.visit_session_id == payload.visit_session_id,
            VisitorActivity.selected_service == "event",
            VisitorActivity.visit_purpose == event.event_name,
        )
        .first()
    )
    if existing_activity is not None and event_selection_matches_activity(
        existing_activity,
        visitor_id=visitor.visitor_id,
        visit_session_id=payload.visit_session_id,
        event_name=event.event_name,
    ):
        return success_response(
            message="Event already selected",
            data=event_payload(event),
        )

    event.event_attendee_count = (event.event_attendee_count or 0) + 1
    db.add(
        VisitorCheckIn(
            visitor_id=visitor.visitor_id,
            visitor_phone=visitor.visitor_phone,
            event_id=event.event_id,
            check_in_status="event_selected",
            match_method="phone",
            selected_service="event",
            face_enrollment_status=None,
        )
    )

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
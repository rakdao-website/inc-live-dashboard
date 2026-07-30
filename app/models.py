from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ============================================================
# Writable base table models
# These map to real tables from INC.session.sql.
# ============================================================


class Zone(Base):
    __tablename__ = "zones"

    zone_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    zone_name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    zone_type: Mapped[str] = mapped_column(String(40), nullable=False)
    is_bookable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("FALSE"),
    )
    is_closed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("FALSE"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    events: Mapped[list["Event"]] = relationship(back_populates="zone")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="zone")


class EcosystemMetric(Base):
    __tablename__ = "ecosystem_metrics"
    __table_args__ = (
        CheckConstraint("active_companies >= 0"),
        CheckConstraint("active_licenses >= 0"),
    )

    ecosystem_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    active_companies: Mapped[int] = mapped_column(Integer, nullable=False)
    active_licenses: Mapped[int] = mapped_column(Integer, nullable=False)
    top_sector: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("event_time_end > event_time_start"),
        CheckConstraint("event_status IN ('upcoming', 'live', 'ended')"),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    zone_id: Mapped[str] = mapped_column(
        String(30),
        ForeignKey("zones.zone_id"),
        nullable=False,
        index=True,
    )
    event_name: Mapped[str] = mapped_column(String(200), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    event_time_start: Mapped[time] = mapped_column(Time, nullable=False)
    event_time_end: Mapped[time] = mapped_column(Time, nullable=False)
    event_location: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        server_default=text("'Event Area'"),
    )
    event_status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        server_default=text("'upcoming'"),
    )
    event_organizer: Mapped[str] = mapped_column(String(150), nullable=False)
    event_attendee_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    zone: Mapped[Zone] = relationship(back_populates="events")


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("booking_type IN ('meeting', 'studio', 'office')"),
        CheckConstraint("booking_time_end > booking_time_start"),
    )

    booking_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    visitor_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("visitors.visitor_id"),
        nullable=True,
        index=True,
    )
    zone_id: Mapped[str] = mapped_column(
        String(30),
        ForeignKey("zones.zone_id"),
        nullable=False,
        index=True,
    )
    booking_type: Mapped[str] = mapped_column(String(10), nullable=False)
    booking_name: Mapped[str] = mapped_column(String(200), nullable=False)
    visitor_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    visitor_phone: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    visitor_email: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    visitor_is_client: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("FALSE"),
    )
    booking_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    booking_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    booking_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    booking_time_start: Mapped[time] = mapped_column(Time, nullable=False)
    booking_time_end: Mapped[time] = mapped_column(Time, nullable=False)

    zone: Mapped[Zone] = relationship(back_populates="bookings")
    visitor: Mapped[Optional["Visitor"]] = relationship(back_populates="bookings")


class Visitor(Base):
    __tablename__ = "visitors"

    visitor_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    visitor_name: Mapped[str] = mapped_column(String(150), nullable=False)
    visitor_phone: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    visitor_email: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    license_number: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, unique=True, index=True)
    visitor_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'visitor'"),
    )
    company_name: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    company_number: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    is_existing_client: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("FALSE"),
    )
    face_reference_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    face_consent_given: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("FALSE"),
    )
    face_consent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    lead_source: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    last_visit_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    bookings: Mapped[list["Booking"]] = relationship(back_populates="visitor")
    check_ins: Mapped[list["VisitorCheckIn"]] = relationship(back_populates="visitor")


class FaceProfile(Base):
    __tablename__ = "face_profiles"

    face_profile_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    visitor_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("visitors.visitor_id"),
        nullable=False,
        index=True,
    )
    face_identifier: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    consent_given: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("FALSE"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class FaceEmbedding(Base):
    """One face embedding vector (JSON array of floats) for a visitor.

    This table is the persistent face gallery: recognition loads all rows
    and matches by cosine similarity, replacing the old embeddings.pkl file.
    """

    __tablename__ = "face_embeddings"

    face_embedding_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    visitor_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("visitors.visitor_id"),
        nullable=True,
        index=True,
    )
    face_identifier: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    embedding: Mapped[str] = mapped_column(Text, nullable=False)
    source_image: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    model_name: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default=text("'buffalo_l'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class UnknownFaceCapture(Base):
    """A face seen at the kiosk/camera that did not match any visitor."""

    __tablename__ = "unknown_face_captures"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'web_searched', 'linked', 'dismissed')"
        ),
    )

    capture_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    image_path: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    best_gallery_score: Mapped[Optional[float]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'pending'"),
    )
    web_search_status: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    linked_visitor_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("visitors.visitor_id"),
        nullable=True,
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    web_matches: Mapped[list["FaceWebMatch"]] = relationship(
        back_populates="capture",
        order_by="FaceWebMatch.rank",
    )


class FaceWebMatch(Base):
    """Top web face-search candidate for an unknown capture (rank 1..N)."""

    __tablename__ = "face_web_matches"

    web_match_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    capture_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("unknown_face_captures.capture_id"),
        nullable=False,
        index=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[Optional[float]] = mapped_column(nullable=True)
    thumbnail_base64: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default=text("'facecheck'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    capture: Mapped[UnknownFaceCapture] = relationship(back_populates="web_matches")


class VisitSession(Base):
    __tablename__ = "visit_sessions"

    visit_session_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    visitor_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("visitors.visitor_id"),
        nullable=True,
        index=True,
    )
    check_in_time: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    recognition_method: Mapped[str] = mapped_column(String(20), nullable=False)
    is_returning_visitor: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("FALSE"),
    )
    previous_visit_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("visit_sessions.visit_session_id"),
        nullable=True,
    )
    current_selected_service: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    visit_purpose: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class VisitorActivity(Base):
    __tablename__ = "visitor_activity"

    visitor_activity_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    visitor_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("visitors.visitor_id"),
        nullable=True,
        index=True,
    )
    visit_session_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("visit_sessions.visit_session_id"),
        nullable=True,
        index=True,
    )
    selected_service: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    visit_purpose: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    previous_selected_service: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class OtherAssistanceRequest(Base):
    __tablename__ = "other_assistance_requests"

    other_assistance_request_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    visitor_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("visitors.visitor_id"),
        nullable=True,
        index=True,
    )
    visit_session_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("visit_sessions.visit_session_id"),
        nullable=True,
    )
    reason: Mapped[str] = mapped_column(String(120), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class VisitorCheckIn(Base):
    __tablename__ = "visitor_check_ins"
    __table_args__ = (
        CheckConstraint(
            "check_in_status IN ("
            "'booking_found', 'no_booking_found', 'new_visitor_registered', "
            "'service_requested', 'event_selected'"
            ")"
        ),
        CheckConstraint("match_method IN ('phone', 'license_number', 'face')"),
        CheckConstraint(
            "selected_service IS NULL OR selected_service IN ("
            "'meeting_room', 'podcast_studio', 'tiktok_studio', "
            "'event', 'business_center', 'other'"
            ")"
        ),
        CheckConstraint(
            "face_enrollment_status IS NULL OR face_enrollment_status IN ("
            "'not_enrolled', 'enrolled', 'failed'"
            ")"
        ),
    )

    check_in_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    visitor_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("visitors.visitor_id"),
        nullable=True,
        index=True,
    )
    visitor_phone: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    booking_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("bookings.booking_id"),
        nullable=True,
        index=True,
    )
    event_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("events.event_id"),
        nullable=True,
        index=True,
    )
    check_in_time: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    check_in_status: Mapped[str] = mapped_column(String(40), nullable=False)
    match_method: Mapped[str] = mapped_column(String(30), nullable=False)
    selected_service: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    face_enrollment_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    visitor: Mapped[Optional[Visitor]] = relationship(back_populates="check_ins")


class ActivityFeed(Base):
    __tablename__ = "activity_feed"
    __table_args__ = (
        CheckConstraint("NOT (event_id IS NOT NULL AND booking_id IS NOT NULL)"),
        CheckConstraint(
            "activity_action IN ('occupied', 'available', 'starts_in_30', "
            "'starts_in_15', 'starts_now', 'license_application_submitted')"
        ),
        CheckConstraint("category IN ('room', 'event', 'company', 'studio')"),
    )

    feed_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    zone_id: Mapped[Optional[str]] = mapped_column(
        String(30),
        ForeignKey("zones.zone_id"),
        nullable=True,
    )
    event_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("events.event_id"),
        nullable=True,
    )
    booking_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("bookings.booking_id"),
        nullable=True,
    )
    activity_action: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[str] = mapped_column(String(10), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        index=True,
    )

    zone: Mapped[Optional[Zone]] = relationship(foreign_keys=[zone_id])
    event: Mapped[Optional[Event]] = relationship(foreign_keys=[event_id])
    booking: Mapped[Optional[Booking]] = relationship(foreign_keys=[booking_id])


# ============================================================
# Read-only view models
# These map to PostgreSQL views from INC.session.sql.
# They are for SELECT queries only.
# ============================================================


class LiveActivityMetric(Base):
    __tablename__ = "live_activity_metrics"

    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    meetings_active: Mapped[int] = mapped_column(Integer)
    zones_occupied: Mapped[int] = mapped_column(Integer)
    zones_total: Mapped[int] = mapped_column(Integer)
    visitors_count: Mapped[int] = mapped_column(Integer)
    events_today_count: Mapped[int] = mapped_column(Integer)


class LiveEvent(Base):
    __tablename__ = "live_events"

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    zone_id: Mapped[str] = mapped_column(String(30))
    event_name: Mapped[str] = mapped_column(String(200))
    event_date: Mapped[date] = mapped_column(Date)
    event_time_start: Mapped[time] = mapped_column(Time)
    event_time_end: Mapped[time] = mapped_column(Time)
    event_location: Mapped[str] = mapped_column(String(120))
    event_organizer: Mapped[str] = mapped_column(String(150))
    event_attendee_count: Mapped[Optional[int]] = mapped_column(Integer)
    event_status: Mapped[str] = mapped_column(String(10))


class LiveBooking(Base):
    __tablename__ = "live_bookings"

    booking_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    zone_id: Mapped[str] = mapped_column(String(30))
    booking_type: Mapped[str] = mapped_column(String(10))
    booking_name: Mapped[str] = mapped_column(String(200))
    booking_start_date: Mapped[date] = mapped_column(Date)
    booking_end_date: Mapped[date] = mapped_column(Date)
    visitor_name: Mapped[Optional[str]] = mapped_column(String(150))
    visitor_phone: Mapped[Optional[str]] = mapped_column(String(40))
    visitor_email: Mapped[Optional[str]] = mapped_column(String(150))
    visitor_is_client: Mapped[bool] = mapped_column(Boolean)
    booking_date: Mapped[date] = mapped_column(Date)
    booking_time_start: Mapped[time] = mapped_column(Time)
    booking_time_end: Mapped[time] = mapped_column(Time)
    booking_status: Mapped[str] = mapped_column(String(10))


class LiveGroundFloorMap(Base):
    __tablename__ = "live_ground_floor_map"

    zone_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    zone_name: Mapped[str] = mapped_column(String(120))
    zone_type: Mapped[str] = mapped_column(String(40))
    zone_status: Mapped[str] = mapped_column(String)
    zone_pulse: Mapped[bool] = mapped_column(Boolean)
    zone_highlight_color: Mapped[str] = mapped_column(String)
    zone_start_time: Mapped[Optional[time]] = mapped_column(Time)
    zone_end_time: Mapped[Optional[time]] = mapped_column(Time)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class AdminZone(Base):
    __tablename__ = "admin_zones"

    zone_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    zone_name: Mapped[str] = mapped_column(String(120))
    zone_type: Mapped[str] = mapped_column(String(40))
    is_bookable: Mapped[bool] = mapped_column(Boolean)
    is_closed: Mapped[bool] = mapped_column(Boolean)
    current_map_status: Mapped[str] = mapped_column(String)
    zone_start_time: Mapped[Optional[time]] = mapped_column(Time)
    zone_end_time: Mapped[Optional[time]] = mapped_column(Time)
    active_booking_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    active_booking_name: Mapped[Optional[str]] = mapped_column(String(200))
    active_booking_type: Mapped[Optional[str]] = mapped_column(String(10))
    zone_pulse: Mapped[bool] = mapped_column(Boolean)
    zone_highlight_color: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class LiveActivityFeed(Base):
    __tablename__ = "live_activity_feed"

    feed_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    category: Mapped[str] = mapped_column(String(10))
    activity_action: Mapped[str] = mapped_column(String(30))
    zone_id: Mapped[Optional[str]] = mapped_column(String(30))
    zone_name: Mapped[Optional[str]] = mapped_column(String(120))
    zone_status: Mapped[Optional[str]] = mapped_column(String)
    event_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    event_name: Mapped[Optional[str]] = mapped_column(String(200))
    booking_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    booking_name: Mapped[Optional[str]] = mapped_column(String(200))
    display_message: Mapped[str] = mapped_column(String)

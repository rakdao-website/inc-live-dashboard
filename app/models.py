from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Time,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ============================================================
# Writable base table models
# These map to real tables from INC.session.sql.
# Do not use these models to create or modify the database schema.
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


class EcosystemMetric(Base):
    __tablename__ = "ecosystem_metrics"

    ecosystem_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    active_companies: Mapped[int] = mapped_column(Integer, nullable=False)
    active_licenses: Mapped[int] = mapped_column(Integer, nullable=False)
    top_sector: Mapped[str] = mapped_column(String(100), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class Sector(Base):
    __tablename__ = "sectors"

    sector_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sector_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    company_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_order: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        unique=True,
    )


class Event(Base):
    __tablename__ = "events"

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    zone_id: Mapped[str] = mapped_column(
        String(30),
        ForeignKey("zones.zone_id"),
        nullable=False,
    )
    event_name: Mapped[str] = mapped_column(String(200), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
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


class Booking(Base):
    __tablename__ = "bookings"

    booking_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    zone_id: Mapped[str] = mapped_column(
        String(30),
        ForeignKey("zones.zone_id"),
        nullable=False,
    )
    booking_type: Mapped[str] = mapped_column(String(10), nullable=False)
    booking_name: Mapped[str] = mapped_column(String(200), nullable=False)
    booking_date: Mapped[date] = mapped_column(Date, nullable=False)
    booking_time_start: Mapped[time] = mapped_column(Time, nullable=False)
    booking_time_end: Mapped[time] = mapped_column(Time, nullable=False)


class ActivityFeed(Base):
    __tablename__ = "activity_feed"

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
    )


# ============================================================
# Read-only view models
# These map to PostgreSQL views from INC.session.sql.
# They are for SELECT queries only.
# Do not insert, update, or delete using these models.
# ============================================================


class LiveActivityMetric(Base):
    __tablename__ = "live_activity_metrics"

    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    meetings_active: Mapped[int] = mapped_column(Integer)
    zones_occupied: Mapped[int] = mapped_column(Integer)
    zones_total: Mapped[int] = mapped_column(Integer)
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

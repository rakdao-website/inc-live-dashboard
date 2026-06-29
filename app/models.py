from datetime import date, datetime, time

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, SmallInteger, String, Time, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Zone(Base):
    __tablename__ = "zones"

    zone_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    zone_name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    zone_type: Mapped[str] = mapped_column(String(40), nullable=False)
    is_bookable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    events: Mapped[list["Event"]] = relationship(back_populates="zone")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="zone")


class EcosystemMetric(Base):
    __tablename__ = "ecosystem_metrics"
    __table_args__ = (
        CheckConstraint("active_companies >= 0"),
        CheckConstraint("active_licenses >= 0"),
    )

    ecosystem_id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    active_companies: Mapped[int] = mapped_column(Integer, nullable=False)
    active_licenses: Mapped[int] = mapped_column(Integer, nullable=False)
    top_sector: Mapped[str] = mapped_column(String(100), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Sector(Base):
    __tablename__ = "sectors"
    __table_args__ = (CheckConstraint("company_count >= 0"), CheckConstraint("display_order > 0"))

    sector_id: Mapped[int] = mapped_column(primary_key=True)
    sector_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    company_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_order: Mapped[int] = mapped_column(SmallInteger, unique=True, nullable=False)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("event_time_end > event_time_start"),
        CheckConstraint("event_status IN ('upcoming', 'live', 'ended')"),
    )

    event_id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[str] = mapped_column(ForeignKey("zones.zone_id"), nullable=False, index=True)
    event_name: Mapped[str] = mapped_column(String(200), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    event_time_start: Mapped[time] = mapped_column(Time, nullable=False)
    event_time_end: Mapped[time] = mapped_column(Time, nullable=False)
    event_location: Mapped[str] = mapped_column(String(120), default="Event Area", nullable=False)
    event_status: Mapped[str] = mapped_column(String(10), default="upcoming", nullable=False)
    event_organizer: Mapped[str] = mapped_column(String(150), nullable=False)
    event_attendee_count: Mapped[int | None] = mapped_column(Integer)

    zone: Mapped[Zone] = relationship(back_populates="events")


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("booking_type IN ('meeting', 'studio', 'office')"),
        CheckConstraint("booking_time_end > booking_time_start"),
    )

    booking_id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[str] = mapped_column(ForeignKey("zones.zone_id"), nullable=False, index=True)
    booking_type: Mapped[str] = mapped_column(String(10), nullable=False)
    booking_name: Mapped[str] = mapped_column(String(200), nullable=False)
    booking_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    booking_time_start: Mapped[time] = mapped_column(Time, nullable=False)
    booking_time_end: Mapped[time] = mapped_column(Time, nullable=False)

    zone: Mapped[Zone] = relationship(back_populates="bookings")


class ActivityFeed(Base):
    __tablename__ = "activity_feed"
    __table_args__ = (
        CheckConstraint("NOT (event_id IS NOT NULL AND booking_id IS NOT NULL)"),
        CheckConstraint("activity_action IN ('occupied', 'available', 'starts_in_30', 'starts_in_15', 'starts_now', 'license_application_submitted')"),
        CheckConstraint("category IN ('room', 'event', 'company', 'studio')"),
    )

    feed_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    zone_id: Mapped[str | None] = mapped_column(ForeignKey("zones.zone_id"))
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.event_id"))
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.booking_id"))
    activity_action: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[str] = mapped_column(String(10), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, index=True)

    zone: Mapped[Zone | None] = relationship(foreign_keys=[zone_id])
    event: Mapped[Event | None] = relationship(foreign_keys=[event_id])
    booking: Mapped[Booking | None] = relationship(foreign_keys=[booking_id])

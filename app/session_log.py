"""Conversation log: one row per kiosk voice conversation, one row per thing said or done.

Written by the kiosk (`/api/kiosk/sessions`), read by staff in the admin panel (`/admin/sessions`).
Emails and phone numbers are masked before anything is stored, so the log never holds a real contact
detail. Rows older than `sessions.retention_days` are deleted.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app import runtime_settings
from app.admin_panel.models import PK
from app.database import Base
from app.privacy_mask import mask_text

MAX_MESSAGE_CHARS = 4000
ROLES = ("visitor", "assistant", "tool", "system")


def _now() -> datetime:
    return datetime.utcnow()


class KioskSession(Base):
    __tablename__ = "kiosk_sessions"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    visitor_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("visitors.visitor_id", ondelete="SET NULL"), nullable=True, index=True)
    visitor_label: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)  # name at the time, so the log still reads after an erasure
    visitor_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'voice'"))
    outcome: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now, index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    messages: Mapped[list["KioskSessionMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan", order_by="KioskSessionMessage.message_id")


class KioskSessionMessage(Base):
    __tablename__ = "kiosk_session_messages"
    __table_args__ = (UniqueConstraint("session_id", "item_id", name="uq_session_item"),)

    message_id: Mapped[int] = mapped_column(PK, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("kiosk_sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    item_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)  # the voice item id; makes re-sends harmless
    role: Mapped[str] = mapped_column(String(12), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    session: Mapped[KioskSession] = relationship(back_populates="messages")


def storing_enabled() -> bool:
    return bool(runtime_settings.get("sessions.store_transcripts"))


def start_session(db: Session, *, visitor_id: int | None, visitor_label: str | None, visitor_type: str | None, channel: str = "voice") -> KioskSession | None:
    if not storing_enabled():
        return None
    purge_old(db)
    row = KioskSession(
        session_id=str(uuid.uuid4()),
        visitor_id=visitor_id,
        visitor_label=(visitor_label or None) and visitor_label[:150],
        visitor_type=visitor_type,
        channel=channel,
    )
    db.add(row)
    db.commit()
    return row


def add_message(db: Session, session_id: str, role: str, content: str, item_id: str | None = None) -> bool:
    """Store one line, masked. Returns False when the session is unknown, ended or the line is a repeat."""
    session = db.get(KioskSession, session_id)
    if session is None or session.ended_at is not None or role not in ROLES:
        return False
    text_value = mask_text(content.strip())[:MAX_MESSAGE_CHARS]
    if not text_value:
        return False
    if item_id:
        existing = db.query(KioskSessionMessage).filter_by(session_id=session_id, item_id=item_id).one_or_none()
        if existing is not None:
            existing.content = text_value  # the same spoken turn arrives again once its text is final
            db.commit()
            return True
    db.add(KioskSessionMessage(session_id=session_id, item_id=item_id, role=role, content=text_value))
    session.message_count = (session.message_count or 0) + 1
    db.commit()
    return True


def end_session(db: Session, session_id: str, outcome: str | None, visitor=None) -> bool:
    session = db.get(KioskSession, session_id)
    if session is None:
        return False
    if session.ended_at is None:
        if visitor is not None and session.visitor_id is None:
            session.visitor_id, session.visitor_label, session.visitor_type = visitor.visitor_id, visitor.visitor_name[:150], visitor.visitor_type
        session.ended_at = _now()
        session.outcome = (outcome or "ended")[:40]
        db.commit()
    return True


def purge_old(db: Session) -> int:
    days = int(runtime_settings.get("sessions.retention_days"))
    cutoff = _now() - timedelta(days=days)
    old = db.query(KioskSession).filter(KioskSession.started_at < cutoff).all()
    for row in old:
        db.delete(row)
    if old:
        db.commit()
    return len(old)

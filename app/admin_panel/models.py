from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# BigInteger keys autoincrement on Postgres; the Integer variant keeps SQLite tests working.
PK = BigInteger().with_variant(Integer, "sqlite")


class AdminUser(Base):
    __tablename__ = "admin_users"
    __table_args__ = (
        CheckConstraint("role IN ('super_user', 'reception', 'reviewer', 'read_only')"),
    )

    user_id: Mapped[int] = mapped_column(PK, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class AdminSession(Base):
    """Server-side record behind the signed cookie, so logout and deactivation take effect at once."""

    __tablename__ = "admin_sessions"

    session_pk: Mapped[int] = mapped_column(PK, primary_key=True)
    session_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("admin_users.user_id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"

    audit_id: Mapped[int] = mapped_column(PK, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), index=True)


class VisitorApproval(Base):
    """A decision record for a visitor created at the kiosk. Pending until a reviewer decides."""

    __tablename__ = "visitor_approvals"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected')"),
        CheckConstraint("source IN ('new_entry', 'web_suggestion')"),
    )

    approval_id: Mapped[int] = mapped_column(PK, primary_key=True)
    visitor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("visitors.visitor_id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'pending'"), index=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    capture_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    chosen_web_match_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    best_gallery_score: Mapped[Optional[float]] = mapped_column(nullable=True)
    entered_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON of what the person typed
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    decided_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    decided_by_username: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    decision_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

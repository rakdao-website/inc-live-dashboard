"""Tamper-evident audit log.

Every new audit row stores `row_hash = SHA-256(previous row_hash + its own content)`. Changing, deleting or
inserting an old row breaks every hash after it, and `verify()` reports where. On PostgreSQL a trigger
(see the migration) also refuses UPDATE and DELETE on the table, so the log is append-only.
Rows written before this existed have no hash and are counted as `unchained`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.admin_panel.clock import utcnow
from app.admin_panel.models import AdminAuditLog

_LOCK_KEY = 7_204_001  # advisory lock number: serialises writers so the chain has one order

CATEGORIES = ("auth", "data_access", "change", "privacy", "system")


def category_for(action: str) -> str:
    a = action.lower()
    if a.startswith(("login.", "logout", "user.password")):
        return "auth"
    if a.endswith((".view", ".list", ".export", ".verify")) or a.startswith("get "):
        return "data_access"
    if "erase" in a or "erasure" in a or a.startswith("privacy.") or a.startswith("delete /admin/visitors"):
        return "privacy"
    if a.startswith(("settings.", "user.", "spacebring.", "approval.", "capture.", "post ", "put ", "patch ", "delete ")):
        return "change"
    return "system"


def _content(row: AdminAuditLog) -> str:
    return json.dumps(
        [row.user_id, row.username, row.role, row.action, row.entity_type, row.entity_id, row.detail, row.ip_address,
         row.category, row.occurred_at.isoformat() if row.occurred_at else None],
        separators=(",", ":"), default=str,
    )


def compute_hash(prev_hash: str | None, row: AdminAuditLog) -> str:
    return hashlib.sha256(((prev_hash or "") + _content(row)).encode()).hexdigest()


@event.listens_for(Session, "before_flush")
def _chain_new_rows(session: Session, _context, _instances) -> None:
    new_rows = [o for o in session.new if isinstance(o, AdminAuditLog)]
    if not new_rows:
        return
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    last = (
        session.query(AdminAuditLog.row_hash)
        .filter(AdminAuditLog.row_hash.isnot(None))
        .order_by(AdminAuditLog.audit_id.desc())
        .limit(1)
        .scalar()
    )
    for row in new_rows:
        if row.occurred_at is None:
            row.occurred_at = utcnow()
        if row.category is None:
            row.category = category_for(row.action)
        row.prev_hash = last
        row.row_hash = last = compute_hash(row.prev_hash, row)


def verify(db: Session) -> dict:
    """Walk the chain in order. `ok` is True when every chained row still matches its hash."""
    unchained = 0
    checked = 0
    previous: str | None = None
    for row in db.query(AdminAuditLog).order_by(AdminAuditLog.audit_id).yield_per(500):
        if row.row_hash is None:
            if checked == 0:
                unchained += 1
                continue
            return {"ok": False, "checked": checked, "unchained": unchained, "broken_at": row.audit_id, "reason": "A row after the chain started has no hash."}
        if row.prev_hash != previous or compute_hash(previous, row) != row.row_hash:
            return {"ok": False, "checked": checked, "unchained": unchained, "broken_at": row.audit_id,
                    "reason": "This row, or one before it, was changed or removed."}
        previous = row.row_hash
        checked += 1
    return {"ok": True, "checked": checked, "unchained": unchained, "broken_at": None, "reason": None}

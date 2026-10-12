"""The kiosk reports each voice conversation here so staff can review it later (public, like the rest of /api/kiosk).

The visitor's name comes from our database, never from the browser, and every line is masked before it is stored.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import session_log
from app.admin_panel.responses import failure, success
from app.database import get_db
from app.models import Visitor

router = APIRouter(prefix="/api/kiosk/sessions", tags=["Kiosk sessions"])


class StartSession(BaseModel):
    visitor_id: Optional[int] = None
    channel: str = Field(default="voice", max_length=20)


class AddMessage(BaseModel):
    role: str = Field(max_length=12)
    text: str = Field(min_length=1, max_length=8000)
    item_id: Optional[str] = Field(default=None, max_length=80)


class EndSession(BaseModel):
    outcome: Optional[str] = Field(default=None, max_length=40)
    visitor_id: Optional[int] = None  # who the visitor turned out to be, if they were identified during the conversation


@router.post("")
def start(payload: StartSession, db: Session = Depends(get_db)):
    visitor = db.get(Visitor, payload.visitor_id) if payload.visitor_id else None
    row = session_log.start_session(
        db,
        visitor_id=visitor.visitor_id if visitor else None,
        visitor_label=visitor.visitor_name if visitor else None,
        visitor_type=visitor.visitor_type if visitor else None,
        channel=payload.channel if payload.channel in ("voice", "kiosk") else "voice",
    )
    return success("Session started", {"session_id": row.session_id if row else None, "logging": row is not None})


@router.post("/{session_id}/messages")
def add_message(session_id: str, payload: AddMessage, db: Session = Depends(get_db)):
    if not session_log.add_message(db, session_id, payload.role, payload.text, payload.item_id):
        return failure(404, "Session not found or already ended.", "SESSION_NOT_OPEN")
    return success("Saved")


@router.post("/{session_id}/end")
def end(session_id: str, payload: EndSession, db: Session = Depends(get_db)):
    if not session_log.end_session(db, session_id, payload.outcome, db.get(Visitor, payload.visitor_id) if payload.visitor_id else None):
        return failure(404, "Session not found.", "SESSION_NOT_FOUND")
    return success("Session ended")

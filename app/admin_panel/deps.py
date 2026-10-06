"""The gate every /admin and /api/face route passes through."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.admin_panel import permissions
from app.admin_panel.clock import utcnow
from app.admin_panel.models import AdminSession, AdminUser
from app.admin_panel.responses import AdminHTTPError
from app.admin_panel.security import hash_session_id, read_token
from app.config import settings
from app.database import get_db

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class AdminPrincipal:
    user_id: int
    username: str
    display_name: str
    role: str
    session_pk: int


def allowed_origins() -> set[str]:
    return {o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()}


def _principal_from_cookie(request: Request, db: Session) -> AdminPrincipal | None:
    session_id = read_token(request.cookies.get(settings.admin_cookie_name))
    if session_id is None:
        return None
    session = (
        db.query(AdminSession)
        .filter(AdminSession.session_hash == hash_session_id(session_id))
        .one_or_none()
    )
    if session is None or session.revoked_at is not None or session.expires_at < utcnow():
        return None
    user = db.get(AdminUser, session.user_id)
    if user is None or not user.is_active:
        return None
    return AdminPrincipal(user.user_id, user.username, user.display_name, user.role, session.session_pk)


def _check_origin(request: Request) -> None:
    """Cookie-authenticated writes must come from an allowed browser origin (CSRF guard)."""
    if request.method not in UNSAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin and origin not in allowed_origins():
        raise AdminHTTPError(403, "Request origin is not allowed.", "ORIGIN_NOT_ALLOWED")


def admin_gate(request: Request, db: Session = Depends(get_db)) -> AdminPrincipal | None:
    """401 without a valid session, 403 when the role may not do this. Fails closed."""
    path = request.url.path
    if path in permissions.PUBLIC_PATHS:
        return None

    principal = _principal_from_cookie(request, db)
    if principal is None:
        raise AdminHTTPError(401, "Sign in to continue.", "NOT_AUTHENTICATED")
    request.state.admin_user = principal
    _check_origin(request)

    if path in permissions.SESSION_ONLY_PATHS:
        return principal

    resource, action = permissions.resource_for(request.method, path)
    if not permissions.is_allowed(principal.role, resource, action):
        raise AdminHTTPError(403, "Your role does not allow this action.", "FORBIDDEN")
    return principal


def current_admin(request: Request, _gate=Depends(admin_gate)) -> AdminPrincipal:
    principal = getattr(request.state, "admin_user", None)
    if principal is None:
        raise AdminHTTPError(401, "Sign in to continue.", "NOT_AUTHENTICATED")
    return principal

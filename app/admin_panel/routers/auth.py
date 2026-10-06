
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.admin_panel import permissions
from app.admin_panel.clock import utcnow
from app.admin_panel.audit import client_ip, record_audit
from app.admin_panel.deps import AdminPrincipal, admin_gate, current_admin
from app.admin_panel.models import AdminSession, AdminUser
from app.admin_panel.rate_limit import login_limiter
from app.admin_panel.responses import failure, success
from app.admin_panel.security import (
    DUMMY_HASH,
    hash_password,
    hash_session_id,
    new_session_id,
    password_problem,
    sign_token,
    verify_password,
)
from app.config import settings
from app.database import get_db
from app.schemas import AdminLoginRequest

router = APIRouter(prefix="/admin/auth", tags=["Admin auth"], dependencies=[Depends(admin_gate)])


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


def user_payload(user: AdminUser | AdminPrincipal) -> dict:
    return {
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "permissions": permissions.permissions_for(user.role),
    }


@router.post("/login")
def login(payload: AdminLoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request) or "unknown"
    username = payload.username.strip().lower()
    keys = (f"ip:{ip}", f"user:{username}")

    wait = login_limiter.retry_after(*keys)
    if wait:
        record_audit(db, None, "login.blocked", "admin_user", username, ip_address=ip, username=username)
        db.commit()
        limited = failure(429, "Too many sign-in attempts. Try again later.", "LOGIN_RATE_LIMITED")
        limited.headers["Retry-After"] = str(wait)
        return limited

    user = db.query(AdminUser).filter(AdminUser.username == username).one_or_none()
    password_ok = verify_password(payload.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not user.is_active or not password_ok:
        login_limiter.record_failure(*keys)
        record_audit(db, None, "login.failed", "admin_user", username, ip_address=ip, username=username)
        db.commit()
        return failure(401, "Invalid username or password", "INVALID_ADMIN_LOGIN")

    login_limiter.reset(*keys)
    now = utcnow()
    expires = now + timedelta(minutes=settings.admin_session_ttl_minutes)
    session_id = new_session_id()
    db.add(
        AdminSession(
            session_hash=hash_session_id(session_id),
            user_id=user.user_id,
            created_at=now,
            expires_at=expires,
            ip_address=ip,
        )
    )
    user.last_login_at = now
    record_audit(db, user, "login.success", "admin_user", user.user_id, ip_address=ip)
    db.commit()

    response.set_cookie(
        settings.admin_cookie_name,
        sign_token(session_id, int(expires.timestamp())),
        max_age=settings.admin_session_ttl_minutes * 60,
        httponly=True,
        secure=settings.admin_cookie_secure,
        samesite="lax",
        path="/",
    )
    return success("Signed in successfully", user_payload(user))


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    principal: AdminPrincipal = Depends(current_admin),
    db: Session = Depends(get_db),
):
    session = db.get(AdminSession, principal.session_pk)
    if session is not None:
        session.revoked_at = utcnow()
    record_audit(db, principal, "logout", "admin_user", principal.user_id, request=request)
    db.commit()
    response.delete_cookie(settings.admin_cookie_name, path="/")
    return success("Signed out")


@router.get("/me")
def me(principal: AdminPrincipal = Depends(current_admin)):
    return success("Current user", user_payload(principal))


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    principal: AdminPrincipal = Depends(current_admin),
    db: Session = Depends(get_db),
):
    user = db.get(AdminUser, principal.user_id)
    if not verify_password(payload.current_password, user.password_hash):
        return failure(400, "Current password is incorrect.", "CURRENT_PASSWORD_WRONG")
    problem = password_problem(payload.new_password)
    if problem:
        return failure(422, problem, "WEAK_PASSWORD")
    user.password_hash = hash_password(payload.new_password)
    user.updated_at = utcnow()
    # End every other session of this user.
    for other in db.query(AdminSession).filter(
        AdminSession.user_id == user.user_id,
        AdminSession.revoked_at.is_(None),
        AdminSession.session_pk != principal.session_pk,
    ):
        other.revoked_at = utcnow()
    record_audit(db, principal, "user.password_changed", "admin_user", user.user_id, request=request)
    db.commit()
    return success("Password changed")

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.admin_panel.clock import utcnow
from app.admin_panel.audit import record_audit
from app.admin_panel.deps import AdminPrincipal, current_admin, admin_gate
from app.admin_panel.models import AdminSession, AdminUser
from app.admin_panel.responses import failure, success
from app.admin_panel.security import hash_password, password_problem
from app.database import get_db

router = APIRouter(prefix="/admin/users", tags=["Admin users"], dependencies=[Depends(admin_gate)])

RoleName = Literal["super_user", "reception", "reviewer", "read_only"]


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9._@-]+$")
    display_name: str = Field(min_length=1, max_length=120)
    role: RoleName
    password: str = Field(min_length=1, max_length=256)


class UserUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    role: Optional[RoleName] = None
    is_active: Optional[bool] = None
    new_password: Optional[str] = Field(default=None, max_length=256)


def _payload(user: AdminUser) -> dict:
    return {
        "user_id": user.user_id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _active_super_users(db: Session) -> int:
    return db.query(AdminUser).filter(AdminUser.role == "super_user", AdminUser.is_active.is_(True)).count()


@router.get("")
def list_users(db: Session = Depends(get_db)):
    users = db.query(AdminUser).order_by(AdminUser.username).all()
    return success("Admin users retrieved", [_payload(u) for u in users])


@router.post("", status_code=201)
def create_user(
    payload: UserCreate,
    request: Request,
    principal: AdminPrincipal = Depends(current_admin),
    db: Session = Depends(get_db),
):
    username = payload.username.strip().lower()
    if db.query(AdminUser).filter(AdminUser.username == username).count():
        return failure(409, "That username is taken.", "USERNAME_EXISTS")
    problem = password_problem(payload.password)
    if problem:
        return failure(422, problem, "WEAK_PASSWORD")
    user = AdminUser(
        username=username,
        display_name=payload.display_name,
        role=payload.role,
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    db.flush()
    record_audit(db, principal, "user.create", "admin_user", user.user_id, {"role": user.role}, request=request)
    db.commit()
    return success("Admin user created", _payload(user))


@router.patch("/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    principal: AdminPrincipal = Depends(current_admin),
    db: Session = Depends(get_db),
):
    user = db.get(AdminUser, user_id)
    if user is None:
        return failure(404, "Admin user not found", "ADMIN_USER_NOT_FOUND")

    losing_super = user.role == "super_user" and user.is_active and (
        (payload.role is not None and payload.role != "super_user") or payload.is_active is False
    )
    if losing_super and _active_super_users(db) <= 1:
        return failure(409, "At least one active super_user must remain.", "LAST_SUPER_USER")

    changed: dict = {}
    if payload.display_name is not None:
        user.display_name = payload.display_name
        changed["display_name"] = payload.display_name
    if payload.role is not None and payload.role != user.role:
        changed["role"] = {"from": user.role, "to": payload.role}
        user.role = payload.role
    if payload.is_active is not None and payload.is_active != user.is_active:
        user.is_active = payload.is_active
        changed["is_active"] = payload.is_active
    if payload.new_password:
        problem = password_problem(payload.new_password)
        if problem:
            return failure(422, problem, "WEAK_PASSWORD")
        user.password_hash = hash_password(payload.new_password)
        changed["password_reset"] = True
    if changed.get("role") or changed.get("is_active") is False or changed.get("password_reset"):
        for session in db.query(AdminSession).filter(
            AdminSession.user_id == user.user_id, AdminSession.revoked_at.is_(None)
        ):
            session.revoked_at = utcnow()
    user.updated_at = utcnow()
    record_audit(db, principal, "user.update", "admin_user", user.user_id, changed, request=request)
    db.commit()
    return success("Admin user updated", _payload(user))

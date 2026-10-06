"""Roles and what they may do. Enforced by `deps.admin_gate` on the backend.

Every request under /admin and /api/face is mapped to a (resource, action)
pair from its path and method. A path with no mapping is `unmapped` and only a
super_user may use it, so a forgotten route fails closed.
"""

from __future__ import annotations

from typing import Literal

Role = Literal["super_user", "reception", "reviewer", "read_only"]
ROLES: tuple[str, ...] = ("super_user", "reception", "reviewer", "read_only")

READ, WRITE = "read", "write"
RW = {READ, WRITE}
R = {READ}

ALL_RESOURCES = (
    "dashboard", "approvals", "captures", "people", "erasure", "bookings", "rooms",
    "events", "activity", "ecosystem", "audit", "integrations", "privacy", "users",
)

ROLE_PERMISSIONS: dict[str, dict[str, set[str]]] = {
    "super_user": {resource: set(RW) for resource in ALL_RESOURCES},
    "reception": {
        "dashboard": R,
        "people": RW,
        "bookings": RW,
        "rooms": RW,
        "events": RW,
        "captures": RW,
        "activity": R,
        "integrations": R,
    },
    "reviewer": {
        "dashboard": R,
        "approvals": RW,
        "captures": RW,
    },
    "read_only": {
        "dashboard": R,
        "people": R,
        "bookings": R,
        "rooms": R,
        "events": R,
        "activity": R,
        "integrations": R,
    },
}

# Roles that may see FaceCheck.ID source links and thumbnails.
WEB_LINK_ROLES = {"super_user", "reviewer"}

# (path prefix, resource). First match wins, so list longer prefixes first.
_PATH_RESOURCES: tuple[tuple[str, str], ...] = (
    ("/admin/dashboard", "dashboard"),
    ("/admin/approvals", "approvals"),
    ("/admin/users", "users"),
    ("/admin/audit-log", "audit"),
    ("/admin/integrations", "integrations"),
    ("/admin/privacy", "privacy"),
    ("/admin/zones", "rooms"),
    ("/admin/events", "events"),
    ("/admin/bookings", "bookings"),
    ("/admin/visitors", "people"),
    ("/admin/visitor-activity", "activity"),
    ("/admin/returning-visitors", "activity"),
    ("/admin/live-activity", "activity"),
    ("/admin/ecosystem", "ecosystem"),
    ("/api/face/recognition-events", "activity"),
    ("/api/face", "captures"),
)

# Routes any signed-in user may call, whatever their role.
SESSION_ONLY_PATHS = {"/admin/auth/me", "/admin/auth/logout", "/admin/auth/change-password", "/admin/health"}
PUBLIC_PATHS = {"/admin/auth/login"}


def is_protected_path(path: str) -> bool:
    return path.startswith("/admin") or path.startswith("/api/face")


def resource_for(method: str, path: str) -> tuple[str, str]:
    action = READ if method.upper() in {"GET", "HEAD", "OPTIONS"} else WRITE
    clean = path.rstrip("/") or "/"
    if method.upper() == "DELETE" and clean.startswith("/admin/visitors/"):
        return "erasure", WRITE
    for prefix, resource in _PATH_RESOURCES:
        if clean == prefix or clean.startswith(prefix + "/"):
            return resource, action
    return "unmapped", action


def is_allowed(role: str, resource: str, action: str) -> bool:
    if resource == "unmapped":
        return role == "super_user"
    return action in ROLE_PERMISSIONS.get(role, {}).get(resource, set())


def can_see_web_links(role: str) -> bool:
    return role in WEB_LINK_ROLES


def permissions_for(role: str) -> dict[str, list[str]]:
    perms = {res: sorted(actions) for res, actions in ROLE_PERMISSIONS.get(role, {}).items()}
    perms["web_links"] = ["read"] if can_see_web_links(role) else []
    return perms

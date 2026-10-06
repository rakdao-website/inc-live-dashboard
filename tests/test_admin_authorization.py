"""Anonymous calls get 401; each role may only do what the matrix allows (enforced server side)."""

import pytest
from fastapi.routing import APIRoute

from app.admin_panel.permissions import PUBLIC_PATHS, is_protected_path
from app.main import app


def all_routes():
    """Every API route with its path, methods and dependency tree (FastAPI includes routers lazily)."""
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route.path, route.methods, route.dependant
        elif hasattr(route, "effective_candidates"):
            for ctx in route.effective_candidates():
                yield ctx.path, ctx.methods, ctx.dependant


def protected_routes():
    for path, methods, _dependant in all_routes():
        if is_protected_path(path) and path not in PUBLIC_PATHS:
            for method in methods - {"HEAD", "OPTIONS"}:
                yield method, path


def concrete(path):
    import re

    return re.sub(r"\{[^}]+\}", "1", path)


def test_there_are_admin_routes_to_check():
    assert len(list(protected_routes())) > 30


@pytest.mark.parametrize("method,path", sorted(protected_routes()))
def test_anonymous_request_is_401(client, method, path):
    response = client.request(method, concrete(path), json={})
    assert response.status_code == 401, f"{method} {path} answered {response.status_code} without a session"
    assert response.json()["error_code"] == "NOT_AUTHENTICATED"


def test_every_protected_route_runs_the_gate():
    from app.admin_panel.deps import admin_gate

    missing = []
    for path, _methods, dependant in all_routes():
        if is_protected_path(path) and path not in PUBLIC_PATHS:
            if not any(d.call is admin_gate for d in dependant.dependencies):
                missing.append(path)
    assert missing == []


# (role, method, path, allowed)
MATRIX = [
    ("super_user", "GET", "/admin/users", True),
    ("reception", "GET", "/admin/users", False),
    ("reviewer", "GET", "/admin/users", False),
    ("read_only", "GET", "/admin/users", False),
    ("super_user", "GET", "/admin/audit-log", True),
    ("reception", "GET", "/admin/audit-log", False),
    ("read_only", "GET", "/admin/audit-log", False),
    ("reviewer", "GET", "/admin/approvals", True),
    ("super_user", "GET", "/admin/approvals", True),
    ("reception", "GET", "/admin/approvals", False),
    ("read_only", "GET", "/admin/approvals", False),
    ("reviewer", "POST", "/admin/approvals/999/approve", True),
    ("reception", "POST", "/admin/approvals/999/reject", False),
    ("reviewer", "GET", "/api/face/captures", True),
    ("reception", "GET", "/api/face/captures", True),
    ("read_only", "GET", "/api/face/captures", False),
    ("reception", "POST", "/api/face/captures/999/dismiss", True),
    ("read_only", "POST", "/api/face/captures/999/dismiss", False),
    ("reviewer", "GET", "/admin/visitors", False),
    ("reception", "GET", "/admin/visitors", True),
    ("read_only", "GET", "/admin/visitors", True),
    ("read_only", "POST", "/admin/visitors", False),
    ("reception", "DELETE", "/admin/visitors/999", False),  # erasure is super_user only
    ("reviewer", "DELETE", "/admin/visitors/999", False),
    ("super_user", "DELETE", "/admin/visitors/999", True),
    ("reception", "PATCH", "/admin/zones/XYZ/close", True),
    ("read_only", "PATCH", "/admin/zones/XYZ/close", False),
    ("read_only", "GET", "/admin/zones", True),
    ("reviewer", "GET", "/admin/zones", False),
    ("reception", "PUT", "/admin/ecosystem/current", False),
    ("reviewer", "GET", "/admin/dashboard/summary", True),
    ("read_only", "GET", "/admin/dashboard/summary", True),
]


@pytest.mark.parametrize("role,method,path,allowed", MATRIX)
def test_role_matrix(login, role, method, path, allowed):
    session = login(role)
    response = session.request(method, path, json={})
    if allowed:
        assert response.status_code != 403, f"{role} should be allowed {method} {path}"
    else:
        assert response.status_code == 403, f"{role} should be refused {method} {path}, got {response.status_code}"
        assert response.json()["error_code"] == "FORBIDDEN"


def test_unmapped_admin_path_is_super_user_only():
    from app.admin_panel import permissions

    resource, action = permissions.resource_for("GET", "/admin/some-new-thing")
    assert resource == "unmapped"
    assert permissions.is_allowed("super_user", resource, action)
    for role in ("reception", "reviewer", "read_only"):
        assert not permissions.is_allowed(role, resource, action)


def test_every_protected_route_maps_to_a_known_resource():
    from app.admin_panel import permissions

    unmapped = [
        (m, p) for m, p in protected_routes()
        if permissions.resource_for(m, p)[0] == "unmapped" and p not in permissions.SESSION_ONLY_PATHS
    ]
    assert unmapped == []


def test_every_role_can_read_its_own_session(login):
    for role in ("reception", "reviewer", "read_only"):
        assert login(role).get("/admin/auth/me").status_code == 200

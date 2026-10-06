"""Shared fixtures for the admin panel tests: an in-memory SQLite database and signed-in clients."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(_type, _compiler, **_kw):
    return "INTEGER"  # lets BIGINT primary keys autoincrement on SQLite


from app import models as _models  # noqa: E402,F401  (registers every table)
from app.admin_panel import audit as audit_module  # noqa: E402
from app.admin_panel.models import AdminUser  # noqa: E402
from app.admin_panel.rate_limit import login_limiter  # noqa: E402
from app.admin_panel.security import hash_password  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "Correct-Horse-9"


@pytest.fixture()
def session_factory(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(audit_module, "session_factory", factory)
    monkeypatch.setattr(settings, "admin_session_secret", "x" * 40)
    login_limiter.clear()
    return factory


@pytest.fixture()
def client(session_factory):
    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    # No `with`: skip the app lifespan, which would touch the real database.
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def db(session_factory):
    with session_factory() as session:
        yield session


def make_user(db, role="super_user", username=None, password=PASSWORD, active=True):
    user = AdminUser(
        username=username or f"{role}-user",
        display_name=f"{role} user",
        role=role,
        password_hash=hash_password(password),
        is_active=active,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture()
def login(client, db):
    """login("reviewer") creates the user, signs in on a fresh client and returns it."""

    def _login(role="super_user"):
        user = make_user(db, role)
        session = TestClient(app)
        response = session.post("/admin/auth/login", json={"username": user.username, "password": PASSWORD})
        assert response.status_code == 200, response.text
        return session

    return _login

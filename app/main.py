import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
import threading

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.admin import router as admin_router
from app.admin_panel import sync_status
from app.admin_panel.audit import AdminAuditMiddleware
from app.admin_panel.responses import AdminHTTPError, admin_http_error_handler
from app.admin_panel.routers import approvals as admin_approvals_router
from app.admin_panel.routers import audit_log as admin_audit_router
from app.admin_panel.routers import auth as admin_auth_router
from app.admin_panel.routers import dashboard as admin_dashboard_router
from app.admin_panel.routers import settings as admin_settings_router
from app.admin_panel.routers import users as admin_users_router
from app.admin_panel.security import get_session_secret
from app import runtime_settings
from app.config import settings
from app.database import Base, SessionLocal, check_database_connection, engine
from app.face_recognition_service import ensure_pgvector_schema
from app.spacebring_client import spacebring_enabled
from app.face_recognition_service import FaceRecognitionUnavailable, get_face_recognition_service
from app.routers.face import router as face_router
from app.routers.kiosk import router as kiosk_router
from app.routers.kiosk_flow import router as kiosk_flow_router
from app.seed import seed_sample_data
from app.voice_agent.realtime_auth import router as realtime_auth_router

FE_TEST_DIR = Path(__file__).resolve().parents[1] / "fe-test"


def success_response(
    message: str = "Request completed successfully",
    data=None,
) -> dict:
    return {
        "success": True,
        "message": message,
        "data": {} if data is None else data,
    }


def error_response(
    message: str,
    error_code: str,
    details=None,
) -> dict:
    return {
        "success": False,
        "message": message,
        "error_code": error_code,
        "details": details,
    }


def warm_face_recognition_model() -> None:
    try:
        get_face_recognition_service().warm_up()
    except FaceRecognitionUnavailable as exc:
        print(f"Face recognition warm-up skipped: {exc}")
    except Exception as exc:
        print(f"Face recognition warm-up failed: {exc}")


logger = logging.getLogger("spacebring.sync")


async def spacebring_sync_loop() -> None:
    """Pull Spacebring bookings into Postgres. On/off and the interval are admin-panel settings."""

    def run_once() -> None:
        with SessionLocal() as db:
            result = sync_status.run_spacebring_sync(db)
        if result.created or result.updated or result.deleted:
            logger.info("Spacebring sync: %s", result)

    while True:
        wait = 15  # while switched off, look again in 15 s
        if runtime_settings.get("spacebring.sync_enabled"):
            try:
                await asyncio.to_thread(run_once)
            except Exception as exc:  # never let the loop die; the next run retries
                logger.warning("Spacebring sync failed: %s", exc)
            wait = runtime_settings.get("spacebring.sync_interval_seconds")
        await asyncio.sleep(wait)


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_session_secret()  # fails at startup in production if ADMIN_SESSION_SECRET is missing
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)
        try:
            ensure_pgvector_schema(engine)
        except Exception as exc:  # pgvector not installed: face matching will report it
            logger.warning("Could not prepare the pgvector face table: %s", exc)
    if settings.seed_sample_data:
        with SessionLocal() as db:
            seed_sample_data(db)
    threading.Thread(target=warm_face_recognition_model, daemon=True).start()
    sync_task = None
    if spacebring_enabled():
        sync_task = asyncio.create_task(spacebring_sync_loop())
    yield
    if sync_task is not None:
        sync_task.cancel()


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)

# Browsers may send cookies only from these exact origins (no "null", no wildcard).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AdminAuditMiddleware)
app.add_exception_handler(AdminHTTPError, admin_http_error_handler)


@app.exception_handler(RequestValidationError)

async def validation_exception_handler(request, exc):

    return JSONResponse(

        status_code=422,

        content=error_response(

            message="Request validation failed",

            error_code="VALIDATION_ERROR",

            details=exc.errors(),

        ),

    )





@app.exception_handler(SQLAlchemyError)

async def sqlalchemy_exception_handler(request, exc):

    return JSONResponse(

        status_code=500,

        content=error_response(

            message="A database error occurred",

            error_code="DATABASE_ERROR",

            details=None,

        ),

    )





@app.get("/")

def root() -> dict:

    return success_response(

        message="Innovation City backend is running",

        data={

            "app_name": settings.app_name,

            "environment": settings.environment,

        },

    )





@app.get("/health")

def health_check() -> dict:

    return success_response(

        message="Application is healthy",

        data={

            "status": "ok",

        },

    )





@app.get("/health/db")

def database_health_check() -> dict:

    check_database_connection()



    return success_response(

        message="Database connection is healthy",

        data={

            "database": "connected",

        },

    )





app.include_router(kiosk_router)

app.include_router(kiosk_flow_router)
app.include_router(face_router)
app.include_router(admin_router)
app.include_router(admin_auth_router.router)
app.include_router(admin_dashboard_router.router)
app.include_router(admin_approvals_router.router)
app.include_router(admin_users_router.router)
app.include_router(admin_settings_router.router)
app.include_router(admin_audit_router.router)

# Local browser smoke tester: camera, face detect, voice room Q&A, bookings.
if FE_TEST_DIR.is_dir():
    app.mount("/fe-test", StaticFiles(directory=str(FE_TEST_DIR), html=True), name="fe-test")

app.include_router(realtime_auth_router, prefix="/voice-agent")




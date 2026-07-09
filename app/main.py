from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.admin import admin_login, router as admin_router
from app.config import settings
from app.database import Base, SessionLocal, check_database_connection, engine
from app.routers.kiosk import router as kiosk_router
from app.routers.kiosk_flow import router as kiosk_flow_router
from app.schemas import AdminLoginRequest
from app.seed import seed_sample_data


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


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)
    if settings.seed_sample_data:
        with SessionLocal() as db:
            seed_sample_data(db)
    yield


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)


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


@app.post("/admin/auth/login")
def admin_auth_login(payload: AdminLoginRequest):
    return admin_login(payload)


app.include_router(kiosk_router)
app.include_router(kiosk_flow_router)
app.include_router(admin_router)

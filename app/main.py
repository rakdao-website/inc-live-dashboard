from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.admin import router as admin_router
from app.config import settings
from app.database import check_database_connection


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


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
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
        message="Innovation City Admin Backend is running",
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


app.include_router(admin_router)

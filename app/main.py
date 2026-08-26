from contextlib import asynccontextmanager
from pathlib import Path
import threading

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.admin import admin_login, router as admin_router
from app.config import settings
from app.database import Base, SessionLocal, check_database_connection, engine
from app.face_recognition_service import FaceRecognitionUnavailable, get_face_recognition_service
from app.routers.face import router as face_router
from app.routers.kiosk import router as kiosk_router
from app.routers.kiosk_flow import router as kiosk_flow_router
from app.schemas import AdminLoginRequest
from app.seed import seed_sample_data

FE_TEST_DIR = Path(__file__).resolve().parents[1] / "fe-test"

from app.voice_agent.initiate import router as initiate_router
from app.voice_agent.converse import router as converse_router
from app.voice_agent.realtime_auth import router as realtime_auth_router

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


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)
    if settings.seed_sample_data:
        with SessionLocal() as db:
            seed_sample_data(db)
    threading.Thread(target=warm_face_recognition_model, daemon=True).start()
    yield


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3002",
        "http://localhost:3003",
        "http://127.0.0.1:3003",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "null",
        "http://localhost:5500",  # common "Live Server" VS Code extension port
        "http://127.0.0.1:5500",
        "http://localhost:5173",  # Vite's default dev server port (realtime agent tester)
        "http://127.0.0.1:5173"

    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
app.include_router(face_router)
app.include_router(admin_router)

# Local browser smoke tester: camera, face detect, voice room Q&A, bookings.
if FE_TEST_DIR.is_dir():
    app.mount("/fe-test", StaticFiles(directory=str(FE_TEST_DIR), html=True), name="fe-test")

app.include_router(admin_router)



app.include_router(initiate_router, prefix="/voice-agent")

app.include_router(converse_router, prefix="/voice-agent")

app.include_router(realtime_auth_router, prefix="/voice-agent")

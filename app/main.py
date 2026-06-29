from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.routers.kiosk import router as kiosk_router
from app.seed import seed_sample_data


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)
    if settings.seed_sample_data:
        with SessionLocal() as db:
            seed_sample_data(db)
    yield


app = FastAPI(title="Innovation City Live Dashboard API", version="1.0.0", lifespan=lifespan)
app.include_router(kiosk_router)


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}

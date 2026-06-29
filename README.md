# Innovation City Live Dashboard API

FastAPI and SQLAlchemy backend for the Ground Floor dashboard MVP. It maps the supplied PostgreSQL data model into Python models and exposes dashboard-ready data for the TV interface.

## Setup

1. Create a PostgreSQL database. In your local pgAdmin setup this is `INC_live_dashboard`.
2. Copy `.env.example` to `.env` and set `DATABASE_URL` if your database credentials differ.
3. Install dependencies: `pip install -r requirements.txt`
4. Start the API: `uvicorn app.main:app --reload`

Open `http://127.0.0.1:8000/docs` for the interactive API documentation.

On first start, the API creates the SQLAlchemy tables and inserts the MVP sample data. Set `AUTO_CREATE_TABLES=false` and `SEED_SAMPLE_DATA=false` in production or when using the existing `INC.session.sql` script.

## Key endpoints

- `GET /api/header` - title, subtitle, date, time, timezone, and live status for the kiosk header
- `GET /api/zones` - current Ground Floor map status
- `GET /api/activity-metrics` - live activity/KPI cards such as occupied zones, active meetings, and today's events
- `GET /api/ecosystem-metrics` - active companies, active licenses, and top sector
- `GET /api/sectors` - sector chart data
- `GET /api/events` - event schedule data with calculated live/upcoming/ended status
- `GET /api/bookings` - booking schedule data with calculated live/upcoming/ended status
- `GET /api/activity-feed` - latest live activity feed items
- This service is deliberately read-only for the kiosk/dashboard. Admin routes for zone controls, events, and bookings are excluded so they can be implemented separately.

## Backend structure

- `app/main.py` starts FastAPI, runs startup setup, and includes routers.
- `app/routers/kiosk.py` contains the read-only kiosk/dashboard endpoints.
- `app/kiosk_schemas.py` contains the kiosk/dashboard response schemas.
- `app/database.py` contains the SQLAlchemy database engine and session setup.
- `app/models.py` contains the shared SQLAlchemy database table models.

This keeps kiosk backend work separate from future admin backend work. An admin backend can be added later as its own router, for example `app/routers/admin.py`, without mixing it into the kiosk endpoints.

The supplied [`INC.session.sql`](INC.session.sql) remains available for direct PostgreSQL setup and its reporting views. The API owns the normal application CRUD flow through SQLAlchemy.

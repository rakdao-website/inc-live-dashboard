# Innovation City Live Dashboard API

FastAPI and SQLAlchemy backend for the Ground Floor dashboard and kiosk check-in system. It maps the supplied PostgreSQL data model into Python models, exposes dashboard-ready data for the TV interface, and powers the kiosk's visitor recognition and check-in flow.

## Setup

1. Create a PostgreSQL database. In your local pgAdmin setup this is `INC_live_dashboard`.
2. Copy `.env.example` to `.env` and set `DATABASE_URL` if your database credentials differ.
3. Start Qdrant (used as the live face-recognition vector store):
   ```
   docker run -d --name qdrant -p 6333:6333 -p 6334:6334 -v qdrant_storage:/qdrant/storage qdrant/qdrant:latest
   ```
4. Install dependencies: `pip install -r requirements.txt` (or `uv pip install -r requirements.txt` if using `uv`)
5. Start the API: `uvicorn app.main:app --reload`

Open `http://127.0.0.1:8000/docs` for the interactive API documentation.

On first start, the API creates the SQLAlchemy tables and inserts the MVP sample data. Set `AUTO_CREATE_TABLES=false` and `SEED_SAMPLE_DATA=false` in production or when using the existing `INC.session.sql` script.

For local admin dashboard sign-in, use the values from `.env` or `.env.example`.
The default development account is username `admin` and password `admin123`.

### Face recognition

Face detection and recognition use InsightFace (`buffalo_l` model pack). The model downloads automatically (~300MB) on the first face-related API call — this can take a minute, and only happens once.

Live face embeddings are stored in Qdrant (collection `face_embeddings`), not directly in Postgres. Postgres still holds a legacy/bulk-import gallery (`face_embeddings` table, used by `scripts/import_existing_faces.py`) plus visitor identity, capture, and audit data.

### Reverse web face search (FaceCheck.ID)

When a scanned face doesn't match anyone in the Qdrant gallery (score below the threshold in `app/face_recognition_service.py`), the kiosk can optionally query [FaceCheck.ID](https://facecheck.id/en/Face-Search/API) for public-web candidate matches, so the visitor can confirm "is this you?" before registering as new. This is off by default and safe to leave off — everything falls through to normal registration if disabled or unconfigured.

Relevant `.env` settings:
```env
FACE_WEB_SEARCH_ENABLED=false
FACE_WEB_SEARCH_PROVIDER=facecheck
FACECHECK_API_TOKEN=
FACE_WEB_SEARCH_TESTING_MODE=true
FACE_WEB_SEARCH_MAX_IMAGES=3
```
`FACE_WEB_SEARCH_TESTING_MODE=true` uses FaceCheck.ID's free demo mode (inaccurate results, no credits consumed) — useful for verifying the integration before enabling real searches. `FACE_WEB_SEARCH_MAX_IMAGES` controls how many of the kiosk's captured frames get uploaded into a single search (multiple photos of the same person do not cost extra credits, per FaceCheck.ID).

## Key endpoints

- `POST /admin/auth/login` - local admin dashboard sign-in
- `GET /api/header` - title, subtitle, date, time, timezone, and live status for the kiosk header
- `GET /api/zones` - current Ground Floor map status
- `GET /api/activity-metrics` - live activity/KPI cards such as occupied zones, active meetings, and today's events
- `GET /api/ecosystem-metrics` - active companies, active licenses, and top sector
- `GET /api/events` - event schedule data with calculated live/upcoming/ended status
- `GET /api/bookings` - booking schedule data with calculated live/upcoming/ended status
- `GET /api/activity-feed` - latest live activity feed items
- `POST /api/kiosk/recognize-face` - scans a face against the Qdrant gallery; falls back to FaceCheck.ID web search when unrecognized (see above)
- `POST /api/kiosk/profiles`, `/api/kiosk/bookings`, `/api/kiosk/visit-sessions`, etc. - kiosk visitor check-in, registration, and booking flow
- `POST /api/face/detect`, `/api/face/captures/{id}/link`, `/api/face/captures/{id}/dismiss` - admin-side review of unrecognized face captures and their web-search candidates

The original dashboard endpoints above remain read-only. Visitor, booking, and kiosk check-in write endpoints live under `/api/kiosk` and `/api/face`, separate from the TV dashboard's read-only data.

## Backend structure

- `app/main.py` starts FastAPI, runs startup setup, and includes routers.
- `app/routers/kiosk.py` contains the read-only kiosk/dashboard endpoints (TV display data).
- `app/routers/kiosk_flow.py` contains the kiosk visitor check-in flow: face recognition, registration, bookings, event selection.
- `app/routers/face.py` contains the admin-facing face review flow: detect, list/link/dismiss unknown captures.
- `app/kiosk_schemas.py` / `app/kiosk_flow_schemas.py` / `app/face_schemas.py` contain the request/response schemas for each router above.
- `app/face_recognition_service.py` wraps InsightFace + Qdrant for face detection, embedding, and matching.
- `app/face_gallery.py` is the legacy Postgres-backed face gallery, used by `scripts/import_existing_faces.py` for bulk enrollment.
- `app/face_web_search.py` integrates the optional FaceCheck.ID reverse image search fallback.
- `app/face_unknown_capture.py` is shared logic for saving an unrecognized face and running the web search against it, used by both `kiosk_flow.py` and `face.py`.
- `app/database.py` contains the SQLAlchemy database engine and session setup.
- `app/models.py` contains the shared SQLAlchemy database table models.
- `app/config.py` contains all environment-driven settings (database, admin auth, room-question LLM provider, TTS, face web search).

The supplied [`INC.session.sql`](INC.session.sql) remains available for direct PostgreSQL setup and its reporting views. The API owns the normal application CRUD flow through SQLAlchemy; additional schema changes (visitors, bookings, face captures, etc.) live as timestamped migration files under `migrations/`.

## Scripts

- `scripts/seed_poc.py --create-tables` - creates tables and seeds demo visitors/zones/events/bookings for local testing.
- `scripts/import_existing_faces.py --dataset ./dataset` - bulk-enrolls face photos from a folder (one subfolder per visitor) into the Qdrant gallery.
- `scripts/migrate_face_embeddings_to_qdrant.py` - one-off migration of any legacy Postgres `face_embeddings` rows into Qdrant.
- `scripts/live_camera_worker.py` - standalone script for watching a physical camera feed and logging recognition events; separate from the kiosk's own in-browser camera flow.

## Tests

Run the automated test suite (mocks the database and face recognition, no live camera or Qdrant server required):
```
pytest tests -q
```
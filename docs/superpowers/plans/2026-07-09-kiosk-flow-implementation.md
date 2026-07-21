# Kiosk Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full Innovation City kiosk visitor flow with backend APIs, additive database changes, kiosk frontend, and admin visitor activity visibility.

**Architecture:** The existing FastAPI backend remains the shared API service. Existing map routes stay under `/api`, existing admin routes stay under `/admin`, and new kiosk routes live under `/api/kiosk`. The kiosk frontend is a new Next.js app in `INC_Kiosk_Frontend`, while the existing admin Next.js app gets one new `Visitor Activity` section.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, PostgreSQL SQL migrations, pytest, Next.js 14, React 18, TypeScript, Tailwind CSS, Vitest.

## Global Constraints

- Work on backend branch `feature/noor-task` in `C:\Users\noor1\OneDrive\Desktop\INC_Live_Dashboard\INC_Live_Dashboard`.
- Work on admin frontend branch `feature/noor-admin` in `C:\Users\noor1\OneDrive\Desktop\INC_Live_Dashboard\INC_Live_Dashboard_Admin_Frontend`.
- Work on kiosk frontend branch `feature/noor-kiosk` in `C:\Users\noor1\OneDrive\Desktop\INC_Live_Dashboard\INC_Kiosk_Frontend`.
- Face recognition is not implemented; expose placeholder recognition only.
- Voice assistance is not implemented; show the required placeholder UI only.
- Database changes must be additive SQL migrations; do not reset or drop existing data.
- The kiosk must not show the map; it only tells visitors that the map screen can guide them.
- Use the existing success/error response envelope shape.
- Keep `.env` local and out of git.

---

## File Structure

Backend:

- Create `migrations/2026_07_09_add_kiosk_flow.sql`: additive schema changes and seed package rows.
- Modify `app/models.py`: new models and extra visitor columns.
- Create `app/kiosk_flow_schemas.py`: request/response models for kiosk routes.
- Create `app/kiosk_flow_services.py`: pure service helpers for lookup, session creation, booking duration calculation, activity creation, and placeholder recognition.
- Create `app/routers/kiosk_flow.py`: `/api/kiosk` endpoints.
- Modify `app/main.py`: include the new kiosk router.
- Modify `app/admin.py`: add visitor activity and returning visitors endpoints.
- Create tests in `tests/test_kiosk_flow_services.py`, `tests/test_kiosk_flow_api.py`, and `tests/test_admin_visitor_activity.py`.

Admin frontend:

- Modify `components/admin/AdminDashboard.tsx`: add `visitor-activity` section, API loading, search/filter UI, and table rendering.
- No broad component split in this pass; keep the existing single-dashboard pattern.

Kiosk frontend:

- Create a Next.js app in `INC_Kiosk_Frontend`.
- Create `app/layout.tsx`, `app/page.tsx`, `app/globals.css`.
- Create `components/kiosk/*` for shell, buttons, fields, cards, modal, and screens.
- Create `lib/api.ts`, `lib/flow.ts`, `lib/time.ts`.
- Create `lib/time.test.ts` and `lib/flow.test.ts`.

---

### Task 1: Backend Schema Migration

**Files:**
- Create: `migrations/2026_07_09_add_kiosk_flow.sql`

**Interfaces:**
- Produces tables/columns consumed by SQLAlchemy models:
  - `visitors.visitor_type`
  - `visitors.company_name`
  - `visitors.company_number`
  - `face_profiles`
  - `visit_sessions`
  - `visitor_activity`
  - `packages`
  - `other_assistance_requests`

- [ ] **Step 1: Write the migration**

```sql
ALTER TABLE visitors
  ADD COLUMN IF NOT EXISTS visitor_type VARCHAR(20) NOT NULL DEFAULT 'visitor',
  ADD COLUMN IF NOT EXISTS company_name VARCHAR(160),
  ADD COLUMN IF NOT EXISTS company_number VARCHAR(80);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'visitors_visitor_type_check'
  ) THEN
    ALTER TABLE visitors ADD CONSTRAINT visitors_visitor_type_check
      CHECK (visitor_type IN ('client', 'visitor'));
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS face_profiles (
  face_profile_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  visitor_id BIGINT NOT NULL REFERENCES visitors(visitor_id),
  face_identifier VARCHAR(160) NOT NULL UNIQUE,
  consent_given BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS visit_sessions (
  visit_session_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  visitor_id BIGINT REFERENCES visitors(visitor_id),
  check_in_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  recognition_method VARCHAR(20) NOT NULL CHECK (recognition_method IN ('face', 'lookup', 'manual')),
  is_returning_visitor BOOLEAN NOT NULL DEFAULT FALSE,
  previous_visit_id BIGINT REFERENCES visit_sessions(visit_session_id),
  current_selected_service VARCHAR(40),
  visit_purpose VARCHAR(160),
  notes TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS visitor_activity (
  visitor_activity_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  visitor_id BIGINT REFERENCES visitors(visitor_id),
  visit_session_id BIGINT REFERENCES visit_sessions(visit_session_id),
  selected_service VARCHAR(40),
  visit_purpose VARCHAR(160),
  previous_selected_service VARCHAR(40),
  notes TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS packages (
  package_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  package_name VARCHAR(160) NOT NULL UNIQUE,
  package_description TEXT NOT NULL,
  price_label VARCHAR(80),
  features TEXT NOT NULL DEFAULT '',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS other_assistance_requests (
  other_assistance_request_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  visitor_id BIGINT REFERENCES visitors(visitor_id),
  visit_session_id BIGINT REFERENCES visit_sessions(visit_session_id),
  reason VARCHAR(120) NOT NULL,
  notes TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_face_profiles_visitor_id ON face_profiles(visitor_id);
CREATE INDEX IF NOT EXISTS ix_visit_sessions_visitor_id ON visit_sessions(visitor_id);
CREATE INDEX IF NOT EXISTS ix_visitor_activity_visitor_id ON visitor_activity(visitor_id);
CREATE INDEX IF NOT EXISTS ix_visitor_activity_visit_session_id ON visitor_activity(visit_session_id);
CREATE INDEX IF NOT EXISTS ix_other_assistance_requests_visitor_id ON other_assistance_requests(visitor_id);

INSERT INTO packages (package_name, package_description, price_label, features, is_active)
VALUES
  ('Business Setup Starter', 'A starter option for founders exploring Innovation City services.', 'Contact CX', 'Company setup guidance;Free zone consultation;Document support', TRUE),
  ('Growth Package', 'A package for teams ready to expand their Innovation City presence.', 'Contact CX', 'License guidance;Workspace options;CX follow-up', TRUE),
  ('Premium Client Support', 'A premium support path for clients needing tailored assistance.', 'Contact CX', 'Priority CX support;Business center guidance;Renewal support', TRUE)
ON CONFLICT (package_name) DO NOTHING;
```

- [ ] **Step 2: Apply migration locally**

Run in pgAdmin against the `INC_Live_Dashboard` database using Query Tool. Open `migrations/2026_07_09_add_kiosk_flow.sql`, paste the full contents, and execute it.

Expected: migration completes without dropping data.

- [ ] **Step 3: Verify schema**

Run:

```powershell
C:\Users\noor1\AppData\Local\Temp\inc-live-dashboard-backend-venv\Scripts\python.exe -c "from app.database import engine; from sqlalchemy import text; c=engine.connect(); print(c.execute(text(\"select count(*) from packages\")).scalar()); c.close()"
```

Expected: prints `3` or higher.

- [ ] **Step 4: Commit**

```powershell
git add migrations/2026_07_09_add_kiosk_flow.sql
git commit -m "Add kiosk flow database migration"
```

---

### Task 2: Backend Models And Schemas

**Files:**
- Modify: `app/models.py`
- Create: `app/kiosk_flow_schemas.py`
- Test: `tests/test_kiosk_flow_services.py`

**Interfaces:**
- Produces SQLAlchemy classes: `FaceProfile`, `VisitSession`, `VisitorActivity`, `Package`, `OtherAssistanceRequest`.
- Produces Pydantic models consumed by router/service tasks:
  - `ProfileLookupRequest`
  - `CreateProfileRequest`
  - `KioskVisitorRead`
  - `VisitSessionCreate`
  - `KioskBookingCreate`
  - `EventSelectionCreate`
  - `OtherAssistanceCreate`

- [ ] **Step 1: Write failing schema tests**

Add tests that import `CreateProfileRequest` and verify:

```python
from app.kiosk_flow_schemas import CreateProfileRequest


def test_client_profile_accepts_license_and_company_fields():
    payload = CreateProfileRequest(
        full_name="Aisha Khan",
        mobile_number="+971501234567",
        email="aisha@example.com",
        visitor_type="client",
        license_number="LIC-123",
        company_name="Innovation Demo",
        company_number="CO-001",
    )

    assert payload.visitor_type == "client"
    assert payload.license_number == "LIC-123"


def test_visitor_profile_clears_license_number():
    payload = CreateProfileRequest(
        full_name="Omar Hassan",
        mobile_number="+971551112233",
        email="omar@example.com",
        visitor_type="visitor",
        license_number="SHOULD-NOT-STAY",
    )

    assert payload.visitor_type == "visitor"
    assert payload.license_number is None
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
C:\Users\noor1\AppData\Local\Temp\inc-live-dashboard-backend-venv\Scripts\python.exe -m pytest tests/test_kiosk_flow_services.py -q
```

Expected: fails because `app.kiosk_flow_schemas` does not exist.

- [ ] **Step 3: Implement models and schemas**

Add new mapped classes in `app/models.py` and create `app/kiosk_flow_schemas.py` with the request/response models named above. Use existing Pydantic v2 patterns from `app/schemas.py`.

- [ ] **Step 4: Run tests to verify pass**

Run:

```powershell
C:\Users\noor1\AppData\Local\Temp\inc-live-dashboard-backend-venv\Scripts\python.exe -m pytest tests/test_kiosk_flow_services.py -q
```

Expected: schema tests pass.

- [ ] **Step 5: Commit**

```powershell
git add app/models.py app/kiosk_flow_schemas.py tests/test_kiosk_flow_services.py
git commit -m "Add kiosk flow models and schemas"
```

---

### Task 3: Backend Kiosk Services And Routes

**Files:**
- Create: `app/kiosk_flow_services.py`
- Create: `app/routers/kiosk_flow.py`
- Modify: `app/main.py`
- Test: `tests/test_kiosk_flow_api.py`

**Interfaces:**
- Consumes schemas and models from Task 2.
- Produces `/api/kiosk` endpoints for the kiosk frontend.

- [ ] **Step 1: Write failing API tests**

Use `fastapi.testclient.TestClient` against `app.main.app`. Cover:

```python
def test_profile_lookup_returns_not_found_for_unknown_profile(client):
    response = client.post(
        "/api/kiosk/profile-lookup",
        json={"full_name": "Unknown Person", "mobile_number": "+971000000000"},
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "VISITOR_NOT_FOUND"


def test_recognize_face_placeholder_returns_success_envelope(client):
    response = client.post("/api/kiosk/recognize-face", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "recognized" in body["data"]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
C:\Users\noor1\AppData\Local\Temp\inc-live-dashboard-backend-venv\Scripts\python.exe -m pytest tests/test_kiosk_flow_api.py -q
```

Expected: fails with route not found.

- [ ] **Step 3: Implement service helpers**

Create helpers:

```python
from datetime import datetime, time, timedelta

from sqlalchemy.orm import Session

from app.models import VisitSession, VisitorActivity


def normalize_phone(value: str) -> str:
    return "".join(str(value or "").split())


def split_first_name(full_name: str) -> str:
    return str(full_name or "").strip().split(" ", 1)[0]


def calculate_end_time(start_time: time, duration_minutes: int) -> time:
    anchor = datetime.combine(datetime.today(), start_time)
    return (anchor + timedelta(minutes=duration_minutes)).time().replace(second=0, microsecond=0)


def find_previous_visit(db: Session, visitor_id: int) -> VisitSession | None:
    return (
        db.query(VisitSession)
        .filter(VisitSession.visitor_id == visitor_id)
        .order_by(VisitSession.check_in_time.desc(), VisitSession.visit_session_id.desc())
        .first()
    )


def create_activity(
    db: Session,
    *,
    visitor_id: int,
    visit_session_id: int | None,
    selected_service: str | None,
    visit_purpose: str | None,
    notes: str | None,
) -> VisitorActivity:
    activity = VisitorActivity(
        visitor_id=visitor_id,
        visit_session_id=visit_session_id,
        selected_service=selected_service,
        visit_purpose=visit_purpose,
        notes=notes,
    )
    db.add(activity)
    return activity
```
```

- [ ] **Step 4: Implement router endpoints**

Implement all routes from the design spec. Use `JSONResponse` for 404/409 where needed and reuse success/error envelope helpers.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
C:\Users\noor1\AppData\Local\Temp\inc-live-dashboard-backend-venv\Scripts\python.exe -m pytest tests/test_kiosk_flow_api.py tests/test_kiosk_flow_services.py -q
```

Expected: all kiosk tests pass.

- [ ] **Step 6: Commit**

```powershell
git add app/kiosk_flow_services.py app/routers/kiosk_flow.py app/main.py tests/test_kiosk_flow_api.py tests/test_kiosk_flow_services.py
git commit -m "Add kiosk flow API"
```

---

### Task 4: Admin Visitor Activity API

**Files:**
- Modify: `app/admin.py`
- Test: `tests/test_admin_visitor_activity.py`

**Interfaces:**
- Consumes `visitor_activity`, `visit_sessions`, `visitors`, and `other_assistance_requests`.
- Produces:
  - `GET /admin/visitor-activity`
  - `GET /admin/returning-visitors`

- [ ] **Step 1: Write failing tests**

Add a test that seeds one visitor, session, and activity, then asserts:

```python
def test_admin_visitor_activity_returns_activity_rows(client):
    response = client.get("/admin/visitor-activity")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert isinstance(body["data"], list)
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
C:\Users\noor1\AppData\Local\Temp\inc-live-dashboard-backend-venv\Scripts\python.exe -m pytest tests/test_admin_visitor_activity.py -q
```

Expected: fails with route not found.

- [ ] **Step 3: Implement endpoints**

Add endpoints to `app/admin.py`. Return rows with:

```python
{
    "visitor_name": str,
    "visitor_phone": str,
    "visitor_email": str | None,
    "visitor_type": str,
    "company_name": str | None,
    "company_number": str | None,
    "last_visit_date": datetime | None,
    "previous_selected_service": str | None,
    "current_visit_time": datetime | None,
    "current_selected_service": str | None,
    "notes": str | None,
}
```

- [ ] **Step 4: Run tests**

Run:

```powershell
C:\Users\noor1\AppData\Local\Temp\inc-live-dashboard-backend-venv\Scripts\python.exe -m pytest tests/test_admin_visitor_activity.py -q
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```powershell
git add app/admin.py tests/test_admin_visitor_activity.py
git commit -m "Add admin visitor activity API"
```

---

### Task 5: Kiosk Frontend Scaffold

**Files:**
- Create in `C:\Users\noor1\OneDrive\Desktop\INC_Live_Dashboard\INC_Kiosk_Frontend`:
  - `package.json`
  - `package-lock.json`
  - `next.config.mjs`
  - `tsconfig.json`
  - `tailwind.config.ts`
  - `postcss.config.mjs`
  - `app/layout.tsx`
  - `app/page.tsx`
  - `app/globals.css`
  - `lib/time.ts`
  - `lib/time.test.ts`

**Interfaces:**
- Produces a runnable Next.js kiosk app on port `3002`.

- [ ] **Step 1: Scaffold app dependencies**

Use the same dependency versions as the admin frontend where practical:

```powershell
npm.cmd init -y
npm.cmd install next@^14.2.5 react@^18.3.1 react-dom@^18.3.1 lucide-react@^0.468.0 clsx@^2.1.1 tailwind-merge@^2.4.0
npm.cmd install -D typescript@^5.5.4 @types/node@^20.14.15 @types/react@^18.3.3 @types/react-dom@^18.3.0 tailwindcss@^3.4.7 postcss@^8.4.39 autoprefixer@^10.4.19 vitest@^2.1.9
```

- [ ] **Step 2: Add scripts**

Set scripts:

```json
{
  "dev": "next dev",
  "build": "next build",
  "start": "next start",
  "test": "vitest run"
}
```

- [ ] **Step 3: Write failing time utility test**

Create `lib/time.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { addMinutesToTime } from "./time";

describe("addMinutesToTime", () => {
  it("calculates the end time from start time and duration", () => {
    expect(addMinutesToTime("10:30", 90)).toBe("12:00");
  });
});
```

- [ ] **Step 4: Run test to verify failure**

Run:

```powershell
npm.cmd test
```

Expected: fails because `lib/time.ts` is missing.

- [ ] **Step 5: Implement minimal utility and app shell**

Create `lib/time.ts` with `addMinutesToTime(start: string, durationMinutes: number): string`.

- [ ] **Step 6: Run test and build**

Run:

```powershell
npm.cmd test
npm.cmd run build
```

Expected: tests and build pass.

- [ ] **Step 7: Commit**

```powershell
git add .
git commit -m "Scaffold kiosk frontend"
```

---

### Task 6: Kiosk Frontend Flow And API Client

**Files:**
- Create/modify in kiosk frontend:
  - `lib/api.ts`
  - `lib/flow.ts`
  - `lib/flow.test.ts`
  - `components/kiosk/KioskShell.tsx`
  - `components/kiosk/KioskButton.tsx`
  - `components/kiosk/KioskField.tsx`
  - `components/kiosk/ServiceCard.tsx`
  - `components/kiosk/VoiceAssistButton.tsx`
  - `components/kiosk/PackagePromotion.tsx`
  - `app/page.tsx`

**Interfaces:**
- Consumes backend `/api/kiosk` routes from Task 3.
- Produces complete kiosk UI flow.

- [ ] **Step 1: Write failing flow tests**

Test pure flow helpers:

```ts
import { describe, expect, it } from "vitest";
import { nextStepAfterRecognition } from "./flow";

describe("nextStepAfterRecognition", () => {
  it("sends recognized visitors to welcome back", () => {
    expect(nextStepAfterRecognition(true)).toBe("welcome-back");
  });

  it("sends unrecognized visitors to profile lookup", () => {
    expect(nextStepAfterRecognition(false)).toBe("profile-lookup");
  });
});
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
npm.cmd test
```

Expected: fails because `lib/flow.ts` is missing.

- [ ] **Step 3: Implement API client**

Create `requestJson<T>(path: string, options?: RequestInit): Promise<T>` matching the admin frontend envelope handling.

- [ ] **Step 4: Implement step-based UI**

Implement all screens listed in the design spec. Keep state local in `app/page.tsx` or a small reducer in `lib/flow.ts`.

- [ ] **Step 5: Implement placeholders**

Face scan button calls `/api/kiosk/recognize-face`; if no match, it goes to profile lookup. Voice assistance button opens a modal with "Voice assistance is starting...".

- [ ] **Step 6: Run tests and build**

Run:

```powershell
npm.cmd test
npm.cmd run build
```

Expected: tests and build pass.

- [ ] **Step 7: Commit**

```powershell
git add .
git commit -m "Build kiosk visitor flow"
```

---

### Task 7: Admin Frontend Visitor Activity Section

**Files:**
- Modify in admin frontend: `components/admin/AdminDashboard.tsx`

**Interfaces:**
- Consumes `GET /admin/visitor-activity`.
- Adds `visitor-activity` section to existing admin navigation.

- [ ] **Step 1: Add a failing/expected type check through build**

Introduce the `VisitorActivity` type and render section references before data loading exists. Run build and expect TypeScript errors for missing state/API variables.

Run:

```powershell
npm.cmd run build
```

Expected: fails until state and loader are complete.

- [ ] **Step 2: Implement activity loading**

Add `VisitorActivity` type, `visitorActivities` state, and `requestJson<VisitorActivity[]>("/admin/visitor-activity")` in `loadData()`.

- [ ] **Step 3: Implement navigation and section**

Add nav item:

```ts
{ id: "visitor-activity", label: "Visitor Activity", icon: Users, hint: "Track returning visitor activity" }
```

Render table columns from the design spec and add search/filter controls.

- [ ] **Step 4: Run admin tests/build**

Run:

```powershell
npm.cmd test
npm.cmd run build
```

Expected: tests and build pass.

- [ ] **Step 5: Commit**

```powershell
git add components/admin/AdminDashboard.tsx
git commit -m "Add visitor activity admin section"
```

---

### Task 8: End-To-End Verification

**Files:**
- No new files required.

**Interfaces:**
- Verifies backend, admin frontend, and kiosk frontend together.

- [ ] **Step 1: Run backend tests**

```powershell
cd "C:\Users\noor1\OneDrive\Desktop\INC_Live_Dashboard\INC_Live_Dashboard"
C:\Users\noor1\AppData\Local\Temp\inc-live-dashboard-backend-venv\Scripts\python.exe -m pytest
```

Expected: all tests pass.

- [ ] **Step 2: Run admin tests/build**

```powershell
cd "C:\Users\noor1\OneDrive\Desktop\INC_Live_Dashboard\INC_Live_Dashboard_Admin_Frontend"
npm.cmd test
npm.cmd run build
```

Expected: tests and build pass.

- [ ] **Step 3: Run kiosk tests/build**

```powershell
cd "C:\Users\noor1\OneDrive\Desktop\INC_Live_Dashboard\INC_Kiosk_Frontend"
npm.cmd test
npm.cmd run build
```

Expected: tests and build pass.

- [ ] **Step 4: Start local services**

Backend:

```powershell
cd "C:\Users\noor1\OneDrive\Desktop\INC_Live_Dashboard\INC_Live_Dashboard"
C:\Users\noor1\AppData\Local\Temp\inc-live-dashboard-backend-venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Admin:

```powershell
cd "C:\Users\noor1\OneDrive\Desktop\INC_Live_Dashboard\INC_Live_Dashboard_Admin_Frontend"
npm.cmd run dev -- -p 3001
```

Kiosk:

```powershell
cd "C:\Users\noor1\OneDrive\Desktop\INC_Live_Dashboard\INC_Kiosk_Frontend"
npm.cmd run dev -- -p 3002
```

- [ ] **Step 5: Manual flow checks**

Open `http://127.0.0.1:3002` and verify:

- Face scan placeholder reaches profile lookup when no visitor is recognized.
- Profile lookup finds existing seeded visitor by name/mobile.
- Registration creates a visitor.
- Consent false does not create a face profile.
- Consent true allows placeholder face profile creation.
- Meeting room, podcast, and TikTok forms submit.
- Event selection submits.
- Other assistance reason submits.
- Thank you screen returns home.

Open `http://127.0.0.1:3001` and verify:

- Visitor Activity section loads.
- New kiosk activity appears.

- [ ] **Step 6: Final commit if verification changes files**

Commit only intentional source/test/config changes. Do not commit `.env`, `.next`, `node_modules`, or local logs.

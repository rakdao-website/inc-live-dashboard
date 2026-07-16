# Innovation City Kiosk Flow Design

## Scope

Build the full Innovation City self-service kiosk flow across:

- `INC_Kiosk_Frontend`: new kiosk frontend application.
- `INC_Live_Dashboard`: shared FastAPI backend and PostgreSQL schema.
- `INC_Live_Dashboard_Admin_Frontend`: admin dashboard activity visibility.

The existing map screen backend remains under `/api`, the existing admin backend remains under `/admin`, and the new kiosk backend will use `/api/kiosk`.

Face recognition and voice assistance are not implemented in this milestone. They will be represented by clean placeholders and service boundaries that can be replaced later.

## Current Context

The backend already has:

- FastAPI and SQLAlchemy.
- PostgreSQL tables for `visitors`, `bookings`, `events`, `visitor_check_ins`, `zones`, `sectors`, `ecosystem_metrics`, and activity feed data.
- Plain SQL migrations in `migrations/`.
- Existing map screen routes in `app/routers/kiosk.py`.
- Existing admin routes in `app/admin.py`.

The admin frontend is a Next.js app with a single dashboard component and existing visitor/booking/event management.

The kiosk frontend repo currently has only a README and should be scaffolded as a new Next.js app. The SVG design asset is the visual source of truth: dark premium kiosk frame, cyan accent color, pixel/grid decorative language, large touch targets, rounded cards, and centered step-based screens.

## Backend Design

Add a new router, `app/routers/kiosk_flow.py`, mounted under `/api/kiosk`.

Core routes:

- `POST /api/kiosk/recognize-face`
  - Placeholder recognition endpoint.
  - For MVP, returns either no match or a deterministic simulated visitor match from existing visitor records.
  - Does not perform real biometrics.

- `POST /api/kiosk/profile-lookup`
  - Looks up visitor by full name and mobile number.
  - If found, creates or returns enough data for the welcome-back flow.

- `POST /api/kiosk/create-profile`
  - Creates visitor profile.
  - Supports visitor type `client` or `visitor`.
  - License number is accepted only for client visitors.
  - Company name and company number are optional for both types.

- `POST /api/kiosk/facial-consent`
  - Saves facial recognition consent on the visitor.
  - Does not create a face profile unless consent is true.

- `POST /api/kiosk/create-face-profile`
  - Placeholder face profile creation.
  - Requires explicit consent.
  - Stores a generated placeholder identifier only.

- `GET /api/kiosk/visitor/{visitor_id}`
  - Returns kiosk-safe visitor details for the welcome-back screen.
  - Includes company details and visitor type.
  - Avoids exposing internal-only fields in the UI.

- `GET /api/kiosk/visitor/{visitor_id}/current-booking`
  - Returns the current or next relevant booking for today, if any.

- `POST /api/kiosk/visit-session`
  - Creates a visit session.
  - Records recognition method: `face`, `lookup`, or `manual`.
  - Links to previous visit if available.

- `POST /api/kiosk/bookings`
  - Creates meeting room, podcast studio, or TikTok studio booking requests.
  - Calculates end time from duration.
  - Saves selected service in activity history.

- `GET /api/kiosk/events/today`
  - Returns today's events with event name, time, location, and short description.

- `POST /api/kiosk/events/select`
  - Saves event selection as current selected service or visit purpose.

- `GET /api/kiosk/packages`
  - Returns active package records.
  - Uses seed records for now, structured for admin editing later.

- `POST /api/kiosk/other-assistance`
  - Saves selected reason and optional notes.
  - Records it in visitor activity.

Add admin routes:

- `GET /admin/visitor-activity`
  - Returns visitor activity rows for CX/admin review.

- `GET /admin/returning-visitors`
  - Returns returning visitor summary data derived from visit sessions and activity.

## Database Design

Use additive SQL migrations only. Do not reset or drop existing tables.

Extend `visitors` with missing profile fields if not present:

- `visitor_type` with values `client` or `visitor`.
- `company_name`.
- `company_number`.

Use existing fields where possible:

- `visitor_name` for full name.
- `visitor_phone` for mobile number.
- `visitor_email`.
- `license_number`.
- `face_consent_given`.
- `face_consent_at`.
- `face_reference_id`.
- `last_visit_at`.

Add new tables:

- `face_profiles`
  - Placeholder face identifier table for future biometric integration.
  - Stores consent state and generated placeholder identifiers only.

- `visit_sessions`
  - One row per kiosk visit.
  - Stores visitor, check-in time, recognition method, returning flag, previous visit reference, current selected service, visit purpose, and notes.

- `visitor_activity`
  - Activity/history table for admin dashboard.
  - Stores selected service, previous selected service, visit purpose, notes, and timestamp.

- `packages`
  - Editable package records.
  - Stores name, description, price label, features text, active flag.

- `other_assistance_requests`
  - Stores other assistance reason and notes.

The existing `visitor_check_ins` table will continue to receive compatibility rows for check-in style actions. The new kiosk flow treats `visit_sessions` and `visitor_activity` as the source for returning-visitor reporting.

## Kiosk Frontend Design

Scaffold a Next.js app in `INC_Kiosk_Frontend`.

The app is a single step-based kiosk flow with local state for:

- Current step.
- Active visitor.
- Active visit session.
- Current selected service.
- Form data.
- Loading/error state.

Reusable components:

- `KioskShell`
- `KioskHeader`
- `PageTitle`
- `PrimaryButton`
- `SecondaryButton`
- `ServiceCard`
- `InputField`
- `ChoiceCard`
- `BookingCard`
- `CompanyDetailsCard`
- `VoiceAssistButton`
- `ScanningState`
- `PackagePromotion`
- `ThankYouScreen`

Screens:

1. Welcome / Face Scan
2. Welcome Back
3. Login / Profile Lookup
4. Create Your Profile
5. Facial Recognition Consent
6. Facial Scan Progress placeholder
7. Service Selection
8. Book Meeting Room
9. Book Podcast Studio
10. Book TikTok Studio
11. Today's Events
12. Explore Business Center
13. Other Assistance
14. Thank You

The kiosk will not show the map. It only shows the message that visitors can access the map screen for guidance.

## Placeholder Behavior

Face recognition:

- UI shows a scanning state.
- Backend placeholder can simulate no match by default.
- A later feature can replace the placeholder recognition service without changing the UI flow.

Voice assistance:

- Any detail-entry screen shows the required voice assistance button.
- Clicking it opens a modal or inline state: "Voice assistance is starting..."
- No speech recognition implementation is included in this milestone.

## Admin Dashboard Design

Add a `Visitor Activity` nav section in the existing admin dashboard.

Show:

- Visitor name.
- Mobile number.
- Email address.
- Visitor type.
- Company name / company number.
- Last visit date.
- Previous selected service / visit purpose.
- Current visit time.
- Current selected service.
- Notes / other assistance request.

Add lightweight search/filter controls:

- Search by name, mobile, company.
- Filter by visitor type.
- Filter by selected service.
- Filter by date.

## Error Handling

Backend:

- Return existing success/error envelope shape.
- Use `404` for missing visitor/event/package.
- Use `409` for booking conflicts.
- Use `422` for validation errors.
- Keep database errors generic at the HTTP boundary.

Frontend:

- Show clear in-screen errors instead of crashing.
- Keep visitors on the current step after recoverable errors.
- Use loading states for API actions.
- Always allow returning to home from final screens.

## Testing

Backend tests:

- Profile lookup found/not found.
- Profile creation for client and visitor.
- Facial consent true/false behavior.
- Face profile only created with consent.
- Visit session creation.
- Booking request creation with duration-to-end-time calculation.
- Event selection saves activity.
- Other assistance saves request and activity.
- Admin visitor activity endpoint returns expected rows.

Frontend tests:

- Utility tests for time/duration calculations.
- API client behavior for success/error envelopes.
- Step reducer or flow state tests if flow logic is extracted.

Manual verification:

- Run backend tests.
- Run kiosk build.
- Run admin build/tests.
- Start backend, admin, and kiosk locally.
- Complete each kiosk path end to end.

## Implementation Order

1. Backend tests for kiosk schemas/services.
2. Add additive SQL migration.
3. Add SQLAlchemy models and Pydantic schemas.
4. Add kiosk backend routes.
5. Add admin visitor activity routes.
6. Scaffold kiosk frontend.
7. Build kiosk flow UI and API client.
8. Add admin activity section.
9. Run tests/builds and verify local flows.

## Out Of Scope

- Real face recognition.
- Real browser speech recognition.
- Package scraping or live package sync from the website.
- Map display inside the kiosk.
- Email notifications.
- Replacing the existing admin dashboard architecture.

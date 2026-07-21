# Face Enrollment During Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register a new kiosk user's face into the backend face database after facial consent.

**Architecture:** Backend adds real face enrollment to the existing `/api/kiosk/face-profile` route by decoding 3 captured images, extracting embeddings with the existing InsightFace service, and storing them under `visitor:{visitor_id}` in `app/embeddings.pkl`. Kiosk captures 3 quick snapshots from the browser camera during the existing scan-progress step and sends them to the backend.

**Tech Stack:** FastAPI, SQLAlchemy, InsightFace/ONNXRuntime, Next.js, React, browser MediaDevices API.

## Global Constraints

- Keep recognition threshold unchanged at `0.50`.
- Use 3 enrollment samples for speed/accuracy balance.
- Keep the temporary recognition buttons working.
- Do not remove the ability to skip facial enrollment after consent prompt.

---

### Task 1: Backend Enrollment Service

**Files:**
- Modify: `app/face_recognition_service.py`
- Test: `tests/test_face_recognition_service.py`

**Interfaces:**
- Produces: `FaceRecognitionService.enroll_images(name: str, images_base64: list[str]) -> int`
- Produces: `FaceDatabase.replace_person(name: str, embeddings: list[Any]) -> None`

- [ ] Write failing tests for replacing embeddings and enrolling decoded images.
- [ ] Implement database save/replace and sample extraction.
- [ ] Run focused tests.

### Task 2: Kiosk Face-Profile API

**Files:**
- Modify: `app/kiosk_flow_schemas.py`
- Modify: `app/routers/kiosk_flow.py`
- Test: `tests/test_kiosk_flow_api.py`

**Interfaces:**
- Consumes: `CreateFaceProfileRequest(visitor_id: int, images_base64: list[str])`
- Produces response data with `sample_count` and `face_identifier`.

- [ ] Write failing API test for enrollment payload.
- [ ] Replace placeholder identifier with `visitor:{visitor_id}`.
- [ ] Keep facial consent validation.
- [ ] Run focused tests.

### Task 3: Kiosk Camera Capture

**Files:**
- Modify: `INC_Kiosk_Frontend/app/page.tsx`

**Interfaces:**
- Consumes: `/api/kiosk/face-profile` with `{ visitor_id, images_base64 }`.

- [ ] Capture 3 JPEG frames from `navigator.mediaDevices.getUserMedia`.
- [ ] Show progress on scan screen.
- [ ] Send images to backend, create visit session, continue to service selection.
- [ ] Show retry/skip controls if capture or enrollment fails.
- [ ] Run TypeScript and kiosk tests.

# Remove Sectors And Polish UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove sector-facing behavior, polish phone and voice entry UI, update Innovation City packages, and improve admin booking/header controls.

**Architecture:** Backend stops exposing or consuming sector endpoints and seeds the four package plans shown in the latest screenshot. Kiosk owns visitor-facing phone, voice, and package presentation. Admin owns booking filters, phone input display, and top-panel layout.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, pytest, Next.js App Router, React, TypeScript, Vitest, Tailwind CSS.

## Global Constraints

- Preserve existing backend API envelopes.
- Keep phone values submitted as a single normalized international string such as `+971501234567`.
- Do not reintroduce the Sectors admin page or map sector chart.
- Keep UI controls compact enough for the existing kiosk 9:16 flow and admin header.

---

### Task 1: Backend Sector Removal And Packages

**Files:**
- Modify: `app/admin.py`
- Modify: `app/routers/kiosk.py`
- Modify: `app/schemas.py`
- Modify: `app/kiosk_schemas.py`
- Modify: `app/services.py`
- Modify: `app/seed.py`
- Modify: `migrations/2026_07_09_add_kiosk_flow.sql`
- Test: `tests/test_kiosk_flow_api.py`

**Interfaces:**
- Consumes: existing `Package` model and `/api/kiosk/packages`.
- Produces: package rows for Idea, Seed, Startup, Growth with AED prices and feature text.

- [ ] Write package-content regression test for `/api/kiosk/packages`.
- [ ] Remove admin and kiosk sector routes/schemas/imports/state.
- [ ] Update seed and migration package rows to match the screenshot.
- [ ] Run backend tests.

### Task 2: Kiosk Phone And Voice UI

**Files:**
- Modify: `INC_Kiosk_Frontend/app/page.tsx`
- Modify: `INC_Kiosk_Frontend/app/globals.css`

**Interfaces:**
- Consumes: existing `requestJson` and voice modal state.
- Produces: page-level voice action and phone selectors whose closed state shows only the code.

- [ ] Replace field-level mic buttons with one page-level voice button where profile details are entered.
- [ ] Make country select option labels include country names but selected closed UI show only the code.
- [ ] Update package cards for the new feature-rich plan content.
- [ ] Run kiosk tests and build.

### Task 3: Admin Filters And Header Polish

**Files:**
- Modify: `INC_Live_Dashboard_Admin_Frontend/components/admin/AdminDashboard.tsx`

**Interfaces:**
- Consumes: existing `zones` and `bookings` arrays.
- Produces: zone-type booking filter, one-line top controls, and phone selectors whose closed state shows only the code.

- [ ] Add booking zone-type filter.
- [ ] Make dark mode and sign out controls single-line.
- [ ] Make `PhoneInput` closed country-code display code-only.
- [ ] Remove remaining sector state and Ecosystem sector selector.
- [ ] Run admin tests and build.

"""Seed people (clients and employees) and enrol their faces from a CSV.

CSV columns (header row required, UTF-8):
  full_name, phone, email, person_type (client|employee), company_name,
  license_number, company_number, manager_email, photo_urls, photo_paths,
  consent_given (yes|no), consent_date, consent_source

photo_urls   direct image links, separated by |
photo_paths  local image files or folders, separated by | (for local testing)

Rules:
  * phone is the unique key; an existing person with the same phone is updated.
  * a face is enrolled only when consent_given is yes (PDPL: no consent, no face).
  * license_number lives on the license holder only (email == manager_email);
    team members find their company through manager_email instead.
  * nothing is written unless apply=True (dry run by default).
"""
from __future__ import annotations

import base64
import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import httpx
from sqlalchemy.orm import Session

from app.kiosk_flow_services import normalize_phone
from app.models import FaceProfile, Visitor

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
PERSON_TYPES = {"client", "employee"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 20.0

COLUMNS = [
    "full_name", "phone", "email", "person_type", "company_name", "license_number",
    "company_number", "manager_email", "photo_urls", "photo_paths",
    "consent_given", "consent_date", "consent_source",
]


@dataclass
class PersonRow:
    line: int
    full_name: str
    phone: str
    email: str | None
    person_type: str
    company_name: str | None
    license_number: str | None
    company_number: str | None
    manager_email: str | None
    photo_urls: list[str]
    photo_paths: list[str]
    consent_given: bool
    consent_date: date | None
    consent_source: str | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PersonResult:
    row: PersonRow
    action: str = "skipped"          # create | update | skipped
    photos_found: int = 0
    faces_enrolled: int = 0
    notes: list[str] = field(default_factory=list)
    spacebring: str | None = None    # linked | no match | not checked

    def line_text(self) -> str:
        name = f"{self.row.full_name:<18}"
        face = (
            f"{self.faces_enrolled} face vector(s)" if self.faces_enrolled
            else ("no consent: face skipped" if not self.row.consent_given else "no face")
        )
        extra = f"  Spacebring: {self.spacebring}" if self.spacebring else ""
        notes = ("  ! " + "; ".join(self.notes)) if self.notes else ""
        return f"{name} {self.row.person_type or '?':<9} {self.action:<8} {self.photos_found} photo(s) -> {face}{extra}{notes}"


# --- parsing -------------------------------------------------------------

def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _split(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split("|") if part.strip()]


def parse_people_csv(path: Path) -> list[PersonRow]:
    rows: list[PersonRow] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = [h.strip().lower() for h in next(reader, [])]
        missing = [c for c in ("full_name", "phone", "person_type") if c not in header]
        if missing:
            raise ValueError(f"CSV header is missing required column(s): {', '.join(missing)}")
        for line_no, cells in enumerate(reader, start=2):
            if not any(cell.strip() for cell in cells):
                continue
            record = {name: (cells[i].strip() if i < len(cells) else "") for i, name in enumerate(header)}
            rows.append(_to_person(line_no, record))
    return rows


def _to_person(line: int, record: dict[str, str]) -> PersonRow:
    errors: list[str] = []
    warnings: list[str] = []
    full_name = record.get("full_name", "").strip()
    phone_raw = record.get("phone", "").strip()
    person_type = record.get("person_type", "").strip().lower()
    consent_text = record.get("consent_given", "").strip().lower()
    consent_date_text = record.get("consent_date", "").strip()
    email = _clean(record.get("email"))
    manager_email = _clean(record.get("manager_email"))
    license_number = _clean(record.get("license_number"))

    if not full_name:
        errors.append("full_name is required")
    if not phone_raw:
        errors.append("phone is required")
    if person_type not in PERSON_TYPES:
        errors.append("person_type must be client or employee")
    if consent_text not in ("", "yes", "no"):
        errors.append("consent_given must be yes or no")
    consent_given = consent_text == "yes"

    consent_date = None
    if consent_date_text:
        try:
            consent_date = date.fromisoformat(consent_date_text)
        except ValueError:
            errors.append("consent_date must be YYYY-MM-DD")
    if consent_given and not consent_date:
        warnings.append("consent_given is yes but consent_date is empty: using today")

    if email:
        email = email.lower()
    if manager_email:
        manager_email = manager_email.lower()
    if license_number and email and manager_email and email != manager_email:
        warnings.append("license_number ignored: it belongs to the license holder (the manager)")
        license_number = None

    return PersonRow(
        line=line, full_name=full_name, phone=normalize_phone(phone_raw) if phone_raw else "",
        email=email, person_type=person_type, company_name=_clean(record.get("company_name")),
        license_number=license_number, company_number=_clean(record.get("company_number")),
        manager_email=manager_email, photo_urls=_split(record.get("photo_urls")),
        photo_paths=_split(record.get("photo_paths")), consent_given=consent_given,
        consent_date=consent_date, consent_source=_clean(record.get("consent_source")),
        errors=errors, warnings=warnings,
    )


# --- photos --------------------------------------------------------------

def _to_data_url(image_bytes: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")


def download_image(url: str) -> bytes:
    if not url.lower().startswith(("https://", "http://")):
        raise ValueError("only http(s) links are supported")
    with httpx.Client(timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = client.get(url)
    response.raise_for_status()
    if len(response.content) > MAX_IMAGE_BYTES:
        raise ValueError("image is larger than 10 MB")
    return response.content


def collect_photos(
    row: PersonRow,
    photos_root: Path,
    fetch: Callable[[str], bytes] = download_image,
) -> tuple[list[str], list[str]]:
    """Returns (images as base64 data URLs, problems)."""
    images: list[str] = []
    problems: list[str] = []

    for raw in row.photo_paths:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = photos_root / path
        if path.is_dir():
            files = sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
            if not files:
                problems.append(f"no images in folder {raw}")
        elif path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            files = [path]
        else:
            problems.append(f"not found or not an image: {raw}")
            continue
        for file in files:
            images.append(_to_data_url(file.read_bytes()))

    for url in row.photo_urls:
        try:
            images.append(_to_data_url(fetch(url)))
        except Exception as exc:  # network, HTTP or size problem: report, keep going
            problems.append(f"could not download {url}: {exc}")
    return images, problems


# --- applying ------------------------------------------------------------

def find_by_phone(db: Session, phone: str) -> Visitor | None:
    for visitor in db.query(Visitor).all():
        if normalize_phone(visitor.visitor_phone) == phone:
            return visitor
    return None


def seed_people(
    db: Session,
    rows: list[PersonRow],
    *,
    photos_root: Path,
    face_service,
    spacebring_client=None,
    apply: bool = False,
    fetch: Callable[[str], bytes] = download_image,
) -> list[PersonResult]:
    results: list[PersonResult] = []
    seen_phones: set[str] = set()

    for row in rows:
        result = PersonResult(row=row)
        results.append(result)
        result.notes.extend(row.warnings)
        if row.errors:
            result.notes.insert(0, "invalid row, skipped (" + "; ".join(row.errors) + ")")
            continue
        if row.phone in seen_phones:
            result.notes.insert(0, "duplicate phone in the file, skipped")
            continue
        seen_phones.add(row.phone)

        existing = find_by_phone(db, row.phone)
        result.action = "update" if existing else "create"

        # faces: only with recorded consent
        embeddings_images: list[str] = []
        if row.consent_given:
            images, problems = collect_photos(row, photos_root, fetch)
            result.photos_found = len(images)
            result.notes.extend(problems)
            for image in images:
                try:
                    face_service.embedding_from_image_base64(image)
                    embeddings_images.append(image)
                except Exception:
                    result.notes.append("a photo has no detectable face")
        elif row.photo_urls or row.photo_paths:
            result.notes.append("photos ignored: no consent")

        customer_id = None
        if spacebring_client is not None:
            customer_id, result.spacebring = _find_spacebring_customer(spacebring_client, row)

        if not apply:
            result.faces_enrolled = len(embeddings_images)
            continue

        with db.begin_nested():
            visitor = existing or Visitor(visitor_name=row.full_name, visitor_phone=row.phone)
            visitor.visitor_name = row.full_name
            visitor.visitor_phone = row.phone
            visitor.visitor_email = row.email
            visitor.visitor_type = row.person_type
            visitor.company_name = row.company_name
            visitor.company_number = row.company_number
            visitor.manager_email = row.manager_email
            visitor.is_existing_client = row.person_type == "client"
            visitor.lead_source = visitor.lead_source or "people_seed"
            if row.license_number:
                visitor.license_number = row.license_number
            if existing is None:
                db.add(visitor)
            db.flush()

            if customer_id:
                visitor.spacebring_customer_id = customer_id

            if row.consent_given:
                visitor.face_consent_given = True
                visitor.face_consent_at = datetime.combine(row.consent_date or date.today(), datetime.min.time())
            if embeddings_images:
                identifier = f"visitor:{visitor.visitor_id}"
                face_service.enroll_images(identifier, embeddings_images)
                visitor.face_reference_id = identifier
                if not db.query(FaceProfile).filter(FaceProfile.face_identifier == identifier).first():
                    db.add(FaceProfile(visitor_id=visitor.visitor_id, face_identifier=identifier, consent_given=True))
                result.faces_enrolled = len(embeddings_images)
    if apply:
        db.commit()
    return results


def _find_spacebring_customer(client, row: PersonRow) -> tuple[str | None, str]:
    """(membership id, text). Manager email finds the company; own email finds the membership."""
    if not row.manager_email:
        return None, "no manager_email"
    try:
        managers = client.find_memberships(email=row.manager_email)
        if not managers:
            return None, "no match (manager email not found)"
        company_id = managers[0].get("companyRef")
        own_email = row.email or row.manager_email
        people = client.find_memberships(email=own_email, company_id=company_id)
        if not people:
            return None, "no match (company found, person not a member)"
        return people[0]["id"], "linked"
    except Exception as exc:
        return None, f"lookup failed ({exc})"

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.database import engine
from app.models import FaceProfile, Visitor
from app.people_seed import collect_photos, parse_people_csv, seed_people

HEADER = ("full_name,phone,email,person_type,company_name,license_number,company_number,"
          "manager_email,photo_urls,photo_paths,consent_given,consent_date,consent_source\n")
JPEG = b"\xff\xd8\xff\xe0fakejpeg"


def write_csv(tmp_path, *lines):
    path = tmp_path / "people.csv"
    path.write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_valid_rows_and_incomplete_rows(tmp_path):
    path = write_csv(
        tmp_path,
        "Ana,0501110001,ana@x.test,client,Ana Co,LIC-1,CN-1,ana@x.test,,,yes,2026-10-06,form",
        "Mujtaba P",  # name only
        "Bad,0501110002,,visitor,,,,,,,maybe,not-a-date,",
    )
    ana, incomplete, bad = parse_people_csv(path)

    assert ana.errors == [] and ana.phone == "+971501110001" and ana.consent_given
    assert incomplete.errors and any("phone" in e for e in incomplete.errors)
    assert any("person_type" in e for e in bad.errors) and any("consent_given" in e for e in bad.errors)
    assert any("consent_date" in e for e in bad.errors)


def test_license_stays_with_the_license_holder(tmp_path):
    path = write_csv(
        tmp_path,
        "Boss,0501110003,boss@x.test,client,Co,LIC-9,CN-9,boss@x.test,,,no,,",
        "Member,0501110004,member@x.test,client,Co,LIC-9,CN-9,boss@x.test,,,no,,",
    )
    boss, member = parse_people_csv(path)
    assert boss.license_number == "LIC-9"
    assert member.license_number is None and member.warnings


def test_missing_required_column_is_an_error(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("full_name,phone\nA,1\n")
    with pytest.raises(ValueError):
        parse_people_csv(path)


def test_photos_from_file_folder_and_link(tmp_path):
    (tmp_path / "ana").mkdir()
    (tmp_path / "ana" / "1.jpg").write_bytes(JPEG)
    (tmp_path / "ana" / "2.png").write_bytes(JPEG)
    (tmp_path / "ana" / "notes.txt").write_text("skip me")
    (tmp_path / "solo.jpg").write_bytes(JPEG)
    path = write_csv(
        tmp_path,
        "Ana,0501110001,,client,,,,,https://ok.test/a.jpg|https://bad.test/b.jpg,ana|solo.jpg|missing.jpg,yes,2026-10-06,form",
    )
    row = parse_people_csv(path)[0]

    def fetch(url):
        if "bad" in url:
            raise RuntimeError("404")
        return JPEG

    images, problems = collect_photos(row, tmp_path, fetch)

    assert len(images) == 4  # folder (2) + file (1) + good link (1)
    assert len(problems) == 2 and any("missing.jpg" in p for p in problems) and any("bad.test" in p for p in problems)


class FakeFaceService:
    def __init__(self):
        self.enrolled = {}

    def embedding_from_image_base64(self, image):
        if "NOFACE" in image:
            raise ValueError("no face")

    def enroll_images(self, identifier, images):
        self.enrolled[identifier] = len(images)


@pytest.fixture
def db():
    try:
        connection = engine.connect()
        outer = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        session.query(Visitor.manager_email).first()
    except Exception:
        pytest.skip("database with the manager_email column is not available")
    yield session
    session.close()
    outer.rollback()
    connection.close()


def test_seed_creates_updates_and_respects_consent(db, tmp_path):
    (tmp_path / "ana").mkdir()
    (tmp_path / "ana" / "1.jpg").write_bytes(JPEG)
    path = write_csv(
        tmp_path,
        "Ana Test,0509990001,ana@x.test,client,Ana Co,LIC-T1,CN-T1,ana@x.test,,ana,yes,2026-10-06,form",
        "No Consent,0509990002,nc@x.test,employee,Innovation City,,,,,ana,no,,",
    )
    rows = parse_people_csv(path)
    service = FakeFaceService()

    dry = seed_people(db, rows, photos_root=tmp_path, face_service=service, apply=False)
    assert [r.action for r in dry] == ["create", "create"]
    assert db.query(Visitor).filter(Visitor.visitor_phone == "+971509990001").first() is None  # dry run writes nothing

    seed_people(db, rows, photos_root=tmp_path, face_service=service, apply=True)

    ana = db.query(Visitor).filter(Visitor.visitor_phone == "+971509990001").one()
    other = db.query(Visitor).filter(Visitor.visitor_phone == "+971509990002").one()
    assert (ana.visitor_type, ana.license_number, ana.manager_email) == ("client", "LIC-T1", "ana@x.test")
    assert ana.face_consent_given and ana.face_reference_id == f"visitor:{ana.visitor_id}"
    assert service.enrolled == {f"visitor:{ana.visitor_id}": 1}
    assert db.query(FaceProfile).filter(FaceProfile.visitor_id == ana.visitor_id).count() == 1
    assert other.visitor_type == "employee" and not other.face_consent_given and other.face_reference_id is None

    rerun = seed_people(db, rows, photos_root=tmp_path, face_service=service, apply=True)  # idempotent
    assert [r.action for r in rerun] == ["update", "update"]
    assert db.query(FaceProfile).filter(FaceProfile.visitor_id == ana.visitor_id).count() == 1


def test_spacebring_link_uses_manager_email_then_own_email():
    from app.people_seed import _find_spacebring_customer
    from app.people_seed import PersonRow

    class Client:
        def find_memberships(self, *, email, company_id=None, **_):
            if email == "boss@x.test" and company_id is None:
                return [{"id": "m-boss", "companyRef": "co-1"}]
            if email == "member@x.test" and company_id == "co-1":
                return [{"id": "m-member", "companyRef": "co-1"}]
            return []

    def row(email, manager):
        return PersonRow(1, "N", "+971500000000", email, "client", None, None, None, manager, [], [], False, None, None)

    assert _find_spacebring_customer(Client(), row("member@x.test", "boss@x.test")) == ("m-member", "linked")
    assert _find_spacebring_customer(Client(), row("other@x.test", "boss@x.test"))[0] is None
    assert _find_spacebring_customer(Client(), row("a@x.test", "nobody@x.test"))[0] is None
    assert _find_spacebring_customer(Client(), row("a@x.test", None))[1] == "no manager_email"

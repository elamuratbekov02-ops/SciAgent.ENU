"""Нақты аттармен жұмыс ережелері: жалған мәлімет тағылмайды, есептегі телефон мен email қосылмайды."""
from __future__ import annotations

import base64
import io
import json
import os
import re
import tempfile
from pathlib import Path

os.environ.setdefault("SCIAGENT_DB", str(Path(tempfile.mkdtemp()) / "test.db"))
os.environ.setdefault("SCIAGENT_UPLOADS", str(Path(tempfile.mkdtemp()) / "uploads"))
os.environ["SCIAGENT_AI"] = "off"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from app import analytics, store  # noqa: E402
from app.main import app  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SEED = json.loads((ROOT / "data" / "seed.json").read_text(encoding="utf-8"))
PUBLIC = json.loads((ROOT / "data" / "staff_public.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def fresh():
    store.seed_if_empty(force=True)
    yield


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def H(pos):
    return {"X-Position": pos}


def test_teachers_come_from_public_portal_and_have_no_invented_data():
    teachers = [p for p in SEED["persons"] if p["role"] == "teacher"]
    assert len(teachers) == len(PUBLIC["staff"]) + 1
    allowed = {d for _, d in PUBLIC["staff"]} | {PUBLIC["head"]["degree"]}
    for t in teachers:
        assert t["on_portal"] and t["degree"] in allowed
        assert not t["phone"] and not t["email"] and not t["group"]


def test_published_authors_stay_as_printed():
    rec = next(r for r in SEED["records"] if r["reported_section"] == "2.3")
    assert rec["fields"]["authors_text"]
    assert "Kurmanov" in json.dumps(SEED["records"], ensure_ascii=False)


def test_only_unreachable_test_contacts_on_prize_rows():
    text = json.dumps(SEED, ensure_ascii=False)
    assert all(e.endswith("example.edu") for e in re.findall(r"[\w.\-]+@[\w.\-]+", text))
    for rec in SEED["records"]:
        if rec["type"] != "prize":
            assert "phone" not in rec["fields"] and "email" not in rec["fields"]
        elif "phone" in rec["fields"]:
            assert rec["fields"]["phone"].startswith("+7 000 000 ")


def test_prize_learners_are_named_as_in_the_report():
    persons = {p["id"]: p for p in SEED["persons"]}
    prizes = [r for r in SEED["records"] if r["type"] == "prize"]
    assert prizes and all(r["fields"]["authors_text"] and r["author_ids"] for r in prizes)
    for rec in prizes:
        for a in rec["author_ids"]:
            surname = persons[a]["display_name"].split()[0]
            assert surname in rec["fields"]["authors_text"] or persons[a]["display_latin"].split()[0] in rec["fields"]["authors_text"], a


def test_invented_diploma_sample_is_not_a_real_person():
    samples = [p for p in SEED["persons"] if p.get("sample")]
    assert len(samples) == 1 and samples[0]["unit"] is None
    assert not any(samples[0]["id"] in r["author_ids"] for r in SEED["records"])


def test_demo_password_also_covers_the_report_sample(client, monkeypatch):
    monkeypatch.setenv("SCIAGENT_DEMO_PASSWORD", "тест-пароль")
    assert client.get("/samples/5_audit_uchin_esep.xlsx").status_code == 401
    assert client.get("/").status_code == 401


def test_invented_items_are_marked_and_belong_only_to_demo_owner():
    owner = next(q["person"] for q in SEED["positions"] if q.get("show_name"))
    for c in SEED["candidates"]:
        assert c["title"].startswith("[Пример]") and c["person"] == owner
    for items in SEED["mock_import"].values():
        for i in items:
            assert i["fields"]["title"].startswith("[Пример]") and i["person"] == owner


def test_only_owner_has_unconfirmed_records_and_no_invented_coauthor_flags():
    owner = next(q["person"] for q in SEED["positions"] if q.get("show_name"))
    unconfirmed = [r for r in SEED["records"] if not r["confirmed"]]
    assert unconfirmed and all(owner in r["author_ids"] for r in unconfirmed)
    assert not any("coauthor_kz" in r["attrs"] for r in SEED["records"])
    row = next(i for i in analytics.indicators("mgmt", 2025) if i["row"] == 18)
    assert row["value"] is None and row["reported"] == "29"


def test_coauthors_are_not_reported_as_unconfirmed(client):
    teachers = client.get("/api/analytics/teachers", headers=H("head")).json()["items"]
    assert all(t["unconfirmed"] == 0 for t in teachers)
    owner = next(q["person"] for q in SEED["positions"] if q.get("show_name"))
    pending = client.get("/api/campaign", headers=H("head")).json()["pending"]
    assert [p["id"] for p in pending] == [owner]


def test_todays_status_does_not_move_a_past_record_to_another_section(client):
    rec = next(r for r in SEED["records"] if r["reported_section"] == "2.4б" and not r["confirmed"])
    preview = client.post("/api/records/preview", json={"type": "article", "fields": {"title": rec["fields"]["title"]}}, headers=H("doctoral")).json()
    assert preview["duplicate"]
    assert preview["record"]["sections"] == ["2.4б"]


def test_only_demo_owner_is_shown_by_name(client):
    assert client.get("/api/bootstrap", headers=H("doctoral")).json()["person"]["name"]
    for pos in ("head", "resp", "director", "science", "teacher", "master", "student"):
        assert client.get("/api/bootstrap", headers=H(pos)).json()["person"]["name"] is None


def test_doctoral_risk_hides_other_people(client):
    head = client.get("/api/analytics/risks", headers=H("head")).json()["doctoral"]
    assert head and all(d["name"].startswith("Докторант ") and not d["supervisors"] for d in head)
    own = client.get("/api/analytics/risks", headers=H("doctoral")).json()["doctoral"]
    assert len(own) == 1 and not own[0]["name"].startswith("Докторант ")


def test_teachers_without_records_are_not_listed(client):
    data = client.get("/api/analytics/teachers", headers=H("head")).json()
    assert 0 < len(data["items"]) < data["portal_total"]
    assert all(t["total"] > 0 or t["students"] + t["masters"] + t["doctorals"] > 0 for t in data["items"])


def test_excel_keeps_printed_authors(client):
    from io import BytesIO

    from openpyxl import load_workbook

    data = client.get("/api/export/f605/mgmt/2025?pos=head").content
    joined = " ".join(str(c.value) for row in load_workbook(BytesIO(data))["Осн. итоги науч. деят-ти ППС"].iter_rows() for c in row if c.value)
    rec = next(r for r in SEED["records"] if r["reported_section"] == "2.3")
    assert rec["fields"]["authors_text"] in joined


def test_demo_password_blocks_access_when_set(client, monkeypatch):
    monkeypatch.setenv("SCIAGENT_DEMO_PASSWORD", "тест-пароль")
    assert client.get("/api/bootstrap").status_code == 401
    token = base64.b64encode("demo:тест-пароль".encode("utf-8")).decode()
    assert client.get("/api/bootstrap", headers={"Authorization": f"Basic {token}"}).status_code == 200
    bad = base64.b64encode(b"demo:wrong").decode()
    assert client.get("/api/bootstrap", headers={"Authorization": f"Basic {bad}"}).status_code == 401


def test_health_check_works_behind_demo_password_and_shows_no_data(client, monkeypatch):
    monkeypatch.setenv("SCIAGENT_DEMO_PASSWORD", "тест-пароль")
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    assert client.get("/").status_code == 401
    assert client.get("/healthz/").status_code == 401


def test_keyword_guess_does_not_replace_the_reported_sdg_count_and_note_stays(client):
    row = next(i for i in analytics.indicators("mgmt", 2025) if i["row"] == 21)
    assert row["value"] is None and row["reported"] == "21"
    sheet = load_workbook(io.BytesIO(client.get("/api/export/f605/mgmt/2025?pos=resp").content))["Анализ НИР факультета"]
    assert sheet["C21"].value == 21
    assert sheet["D31"].value == "39462,957 постдок"


def test_new_tagged_record_adds_to_the_reported_count_instead_of_replacing_it(client):
    body = {"type": "article", "attrs": {"index": "koksnvo", "sdg": ["4"], "coauthor_kz": True, "coauthor_foreign": False},
            "fields": {"title": "[Пример] Новая статья с отметками", "source": "Вестник (пример)", "year": "2025", "issue": "1", "pages": "1-9", "issn": "2345-6787"}}
    rid = client.post("/api/records", json=body, headers=H("teacher")).json()["record"]["id"]
    client.post(f"/api/records/{rid}/submit", json={}, headers=H("teacher"))
    client.post(f"/api/records/{rid}/approve", json={}, headers=H("head"))
    rows = {i["row"]: i for i in analytics.indicators("mgmt", 2025)}
    assert rows[21]["value"] == 22 and rows[18]["value"] == 30 and rows[19]["value"] == 5
    assert rows[20]["value"] is None

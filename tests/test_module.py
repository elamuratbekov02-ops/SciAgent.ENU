"""Модуль форматы: ресми Excel пішімі, ағынды агент, рөлге сай диаграмма мен файл, өрісті тексеру."""
from __future__ import annotations

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

from app import agent, store  # noqa: E402
from app.main import app  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


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


def position(pos):
    return next(p for p in store.kv_get("positions") if p["id"] == pos)


def events(client, text, pos):
    body = client.post("/api/agent/stream", data={"session": "m", "text": text}, headers=H(pos)).text
    return [json.loads(x[6:]) for x in body.split("\n\n") if x.startswith("data: ")]


def test_excel_keeps_official_format(client):
    wb = load_workbook(io.BytesIO(client.get("/api/export/f605/mgmt/2025?pos=head").content))
    assert wb["Титульный"]["A14"].value == "ОТЧЕТ" and wb["Титульный"]["A14"].font.name == "Times New Roman" and wb["Титульный"]["A14"].font.sz == 16
    ws = wb["Осн. итоги науч. деят-ти ППС"]
    assert ws.page_setup.orientation == "landscape" and ws.page_setup.scale == 40
    assert round(ws.column_dimensions["C"].width, 1) == 48.8
    assert "A1:I1" in {str(m) for m in ws.merged_cells.ranges}
    assert ws["A2"].font.name == "Times New Roman" and not ws["A2"].fill.fill_type
    assert ws["C7"].value and ws["C7"].font.name == "Times New Roman"


def test_blank_template_holds_no_contacts_or_learner_data():
    wb = load_workbook(ROOT / "data" / "f605_template.xlsx")
    assert "Лист1" not in wb.sheetnames
    values = [str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value is not None]
    text = " ".join(values)
    assert "@" not in text and not any(v.startswith("=") for v in values)
    assert not re.search(r"(?:\+?7|8)[\s\-(]*7\d{2}[\s\-)]*\d{3}", text)
    seed = json.loads((ROOT / "data" / "seed.json").read_text(encoding="utf-8"))
    prize_title = next(r["fields"]["event"] for r in seed["records"] if r["type"] == "prize" and r["fields"].get("event"))
    assert prize_title not in text


def test_stream_sends_steps_chart_and_done(client):
    ev = events(client, "Покажи диаграмму по преподавателям", "head")
    assert [e["type"] for e in ev][-1] == "done"
    chart = next(e["chart"] for e in ev if e["type"] == "chart")
    assert len(chart["rows"]) == 10 and chart["series"][0]["key"] == "scopus"
    assert any(e["type"] == "step" for e in ev)


def test_charts_and_files_respect_roles(client):
    assert not any(e["type"] == "chart" for e in events(client, "Покажи диаграмму по преподавателям", "student"))
    assert agent.chart_for("by_teacher", position("student")) is None
    assert agent.chart_for("compare", position("head")) is None
    assert agent.chart_for("compare", position("director"))["rows"]
    assert agent.make_file("f605", position("student"))["ok"] is False
    assert agent.make_file("my_list", position("student"))["ok"] is True
    assert agent.make_file("f605", position("head"))["ok"] is True
    assert agent.make_file("summary", position("head"))["ok"] is False


def test_tools_keep_personal_data_out_of_model_results():
    found = agent.search_records({"query": "", "only_mine": False}, position("head"))
    assert found["found"] > 0 and "authors" not in found["items"][0]
    assert all("name" not in d for d in agent.stats_for("doctoral", position("head"))["doctoral"])
    seed = json.loads((ROOT / "data" / "seed.json").read_text(encoding="utf-8"))
    learner = next(p for p in seed["persons"] if p["role"] == "student" and not p.get("sample"))
    assert agent.find_person({"name": learner["display_name"]}, position("head"))["name"] is None
    teacher = next(p for p in seed["persons"] if p["role"] == "teacher" and p["on_portal"])
    assert agent.find_person({"name": teacher["display_name"]}, position("head"))["name"] == teacher["display_name"]


def test_quotes_are_checked_against_the_document():
    fields = {"title": "Digital reporting", "year": "2031", "source": "Journal of Nothing"}
    proof = {"title": {"quote": "Digital reporting", "page": 1}, "source": {"quote": "Journal of Nothing", "page": 1}}
    checks, mismatches = agent._verify_fields(fields, proof, "Digital  reporting: a study. Published 2025.")
    assert checks["title"] == "document" and checks["source"] == "unverified" and checks["year"] == "unverified"
    assert mismatches == []


def test_several_dois_make_several_cards(client, monkeypatch):
    def fake(doi):
        return {"type": "article", "fields": {"title": f"Статья {doi}", "doi": doi, "year": "2025"}, "authors": [], "verified_by": "crossref"}

    monkeypatch.setattr(agent.integrations, "crossref_by_doi", fake)
    ev = events(client, "10.1000/aaa 10.1000/bbb", "doctoral")
    drafts = [e["draft"] for e in ev if e["type"] == "draft"]
    assert len(drafts) == 2 and drafts[0]["payload"]["ai"]["checks"]["title"] == "crossref"


def test_explain_section_names_list_and_document():
    data = agent.explain_section({"type": "prize", "attrs": {"region": "cis"}}, position("student"))
    assert data["sections"][0]["id"] == "3.7" and data["sections"][0]["required_document"] == "подтверждающий документ"


def test_readiness_only_for_managers():
    assert "note" in agent.report_readiness(position("student"))
    assert agent.report_readiness(position("head"))["records"] > 0


def test_scientists_page_lists_public_names_only(client):
    items = client.get("/api/scientists", headers=H("doctoral")).json()["items"]
    assert items and set(items[0]) == {"id", "name", "degree"}

"""Негізгі логика тесттері: бағыттау, тексеру, рөлдер, есеп құрылымы, агент (сынақ сервермен)."""
from __future__ import annotations

import io
import json
import os
import re
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

os.environ["SCIAGENT_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")
os.environ["SCIAGENT_UPLOADS"] = str(Path(tempfile.mkdtemp()) / "uploads")
os.environ["SCIAGENT_AI"] = "off"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from app import agent, analytics, catalog, services, store, validators  # noqa: E402
from app.main import app  # noqa: E402
from app.names import match_person, parse_people, same_person, split_authors_supervisor  # noqa: E402

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


def test_route_covers_all_form_lists():
    schema = json.loads((ROOT / "data" / "form_schema.json").read_text(encoding="utf-8"))
    ids = [i["id"] for s in schema["sheets"].values() for i in s["items"] if i.get("header")]
    assert len(ids) == 56
    for bid in ids:
        rec_type, role, attrs = catalog.attrs_from_block(bid)
        assert catalog.route(rec_type, role, attrs) == bid, bid


def test_issn_isbn_checksums():
    assert validators.issn_ok("2146-4553")
    assert not validators.issn_ok("2146-4554")
    assert validators.issn_ok("1817-728X")
    assert validators.isbn_ok("978-601-7625-79-5")
    assert not validators.isbn_ok("978-601-326-677-4")


def test_names_transliteration_and_typos():
    assert same_person({"surname": "Мухияева", "initials": "ДМ"}, {"surname": "Mukhiyayeva", "initials": "D"})
    assert same_person({"surname": "Толысбаев", "initials": "БС"}, {"surname": "Тоысбаев", "initials": "БС"})
    assert not same_person({"surname": "Курманов", "initials": "Н"}, {"surname": "Курманов", "initials": "А"})
    assert [p["surname"] for p in parse_people("Каримбаева Г.Ж.,Сейтхожина Д.А Набиева М.Т.")] == ["Каримбаева", "Сейтхожина", "Набиева"]
    authors, boss = split_authors_supervisor("Иванов И. Ғылыми жетеқшісі Петров П.П.")
    assert boss.startswith("Петров") and authors.startswith("Иванов")
    directory = [{"id": "x", "display_name": "Сапаров А.Б.", "aliases": ["Сапаров А.Б.", "Saparov A.B."]}]
    assert match_person("A. Saparov", directory)["person_id"] == "x"
    assert match_person("Сапарова Г.", directory)["person_id"] is None


def test_seed_keeps_report_counts():
    rows = store.records(year=2025, approved_only=True)
    assert len(rows) == 164
    ov = analytics.overview_for(rows)
    assert ov["pps_pubs"] == 56
    assert ov["pps_scopus"] == 12


def test_merge_all_gives_49_unique_teacher_publications(client):
    before = analytics.overview("mgmt", 2025)["raw"]["pps_pubs"]
    assert before == 56
    assert client.post("/api/duplicates/merge-all", headers=H("resp")).status_code == 200
    after = analytics.overview("mgmt", 2025)["raw"]
    assert after["pps_pubs"] == 49
    assert after["koksnvo"] < 35


def test_review_queue_finds_known_problems():
    q = services.review_queue()
    assert q["counts"]["ISSN_CHECKSUM"] >= 3
    assert q["counts"]["PLACE_MISMATCH"] >= 1
    assert q["counts"]["JOURNAL_IN_CONFERENCE"] >= 3
    assert q["counts"]["PRIZE_CONFLICT"] >= 1
    assert q["counts"]["ISBN_SHARED"] >= 12
    assert q["auto_ok"] > 0
    assert any(d["kind"] == "exact" for d in q["duplicates"])


def test_fix_moves_boston_conference_abroad(client):
    q = services.review_queue()
    item = next(i for i in q["items"] if any(x["code"] == "PLACE_MISMATCH" for x in i["issues"]) and i["type"] == "conference")
    r = client.post(f"/api/records/{item['id']}/fix", json={"code": "PLACE_MISMATCH"}, headers=H("resp"))
    assert r.status_code == 200
    assert r.json()["record"]["sections"][0].endswith(".5") or r.json()["record"]["sections"][0] == "2.6"


def test_roles_limit_visibility(client):
    head = client.get("/api/records", headers=H("head")).json()["total"]
    doctoral = client.get("/api/records", headers=H("doctoral")).json()
    assert head >= 150
    assert 0 < doctoral["total"] < head
    other = next(c for c in client.get("/api/records", headers=H("head")).json()["items"] if c["id"] not in {x["id"] for x in doctoral["items"]})
    assert client.get(f"/api/records/{other['id']}", headers=H("doctoral")).status_code == 403
    assert client.get("/api/analytics/overview", headers=H("doctoral")).status_code == 403
    assert client.get("/api/analytics/overview", headers=H("head")).status_code == 200
    assert client.get("/api/analytics/compare", headers=H("head")).status_code == 403
    assert client.get("/api/analytics/compare?parent=uni", headers=H("director")).status_code == 403
    assert client.get("/api/analytics/compare?parent=uni", headers=H("science")).status_code == 200
    assert client.post("/api/duplicates/merge-all", headers=H("student")).status_code == 403


def test_contact_data_hidden_from_head_visible_to_responsible(client):
    rows = store.records(unit="mgmt", year=2025)
    prize = next(r for r in rows if r["type"] == "prize" and r["fields"].get("phone"))
    head = client.get(f"/api/records/{prize['id']}", headers=H("head")).json()
    resp = client.get(f"/api/records/{prize['id']}", headers=H("resp")).json()
    assert head["record"]["fields"]["phone"] == "•••"
    assert resp["record"]["fields"]["phone"].startswith("+7 000")
    log = client.get("/api/log", headers=H("head")).json()["items"]
    assert any(i["action"] == "Открыты контактные данные" for i in log)


def test_form_create_routes_and_notifies_coauthor(client):
    persons = store.persons()
    master = next(p for p in persons.values() if p["role"] == "master" and p.get("unit") == "mgmt")
    payload = {"type": "article", "attrs": {"index": "scopus"},
               "fields": {"title": "A brand new test article on digital management", "source": "Test Journal", "year": "2026", "pages": "1-10", "issn": "2146-4553"},
               "author_ids": [master["id"]]}
    preview = client.post("/api/records/preview", json=payload, headers=H("teacher")).json()
    assert set(preview["record"]["sections"]) == {"2.3", "4.2"}
    created = client.post("/api/records", json=payload, headers=H("teacher")).json()
    assert created["merged"] is False
    assert any("соавтор" in n["text"] for n in store.notifications({"person": master["id"], "role": "x", "unit": "x"}))


def test_duplicate_entry_is_not_saved_twice(client):
    rows = store.records(unit="mgmt", year=2025)
    existing = next(r for r in rows if r["type"] == "article" and r["attrs"].get("index") == "scopus")
    payload = {"type": "article", "attrs": {"index": "scopus"}, "fields": {"title": existing["fields"]["title"], "source": "X", "year": "2025", "pages": "1-2", "issn": "2146-4553", "doi": "10.1/test"}}
    created = client.post("/api/records", json=payload, headers=H("teacher")).json()
    assert created["merged"] is True
    assert len(store.records(unit="mgmt", year=2025, approved_only=True)) == 164


def test_report_workflow_and_frozen_version(client):
    url = "/api/report/mgmt/2025/transition"
    assert client.post(url, json={"action": "approve"}, headers=H("head")).status_code == 400
    blocked = client.post(url, json={"action": "submit"}, headers=H("resp"))
    assert blocked.status_code == 409
    assert client.post(url, json={"action": "submit", "force": True}, headers=H("resp")).json()["status"] == "на согласовании"
    assert client.post(url, json={"action": "sign"}, headers=H("director")).status_code == 400
    assert client.post(url, json={"action": "approve", "protocol": {"no": "5", "date": "12.01.2026"}}, headers=H("head")).json()["status"] == "на подписании"
    signed = client.post(url, json={"action": "sign"}, headers=H("director")).json()
    assert signed["status"] == "согласовано" and signed["version"] == 1
    before = client.get("/api/export/f605/mgmt/2025?pos=head&version=1").content
    assert client.post("/api/duplicates/merge-all", headers=H("resp")).status_code == 409
    assert client.post(url, json={"action": "return", "note": "уточнить"}, headers=H("director")).json()["status"] == "на доработке"
    client.post("/api/duplicates/merge-all", headers=H("resp"))
    report = client.get("/api/report/mgmt/2025", headers=H("head")).json()
    assert report["diff"]["indicators"]
    after = client.get("/api/export/f605/mgmt/2025?pos=head&version=1").content
    wb1, wb2 = load_workbook(io.BytesIO(before)), load_workbook(io.BytesIO(after))
    assert [c.value for c in wb1["Анализ НИР факультета"]["C"]] == [c.value for c in wb2["Анализ НИР факультета"]["C"]]


def test_excel_matches_form_structure(client):
    data = client.get("/api/export/f605/mgmt/2025?pos=resp").content
    wb = load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ["Титульный", "Научный потенциал", "НИР студентов", "Осн. итоги науч. деят-ти ППС", "НИР магистрантов", "НИР докторантов", "Анализ НИР факультета"]
    schema = json.loads((ROOT / "data" / "form_schema.json").read_text(encoding="utf-8"))
    for name, sheet in schema["sheets"].items():
        ws = wb[name]
        text = {re.sub(r"[ \t]+", " ", str(c.value)).strip() for row in ws.iter_rows() for c in row if c.value is not None}
        for item in sheet["items"]:
            assert item["title"] in text, item["title"][:40]
            for h in item.get("header") or []:
                assert h["label"] in text, h["label"][:40]
    titles = sum(1 for row in wb["Осн. итоги науч. деят-ти ППС"].iter_rows() if row[3].value and row[2].value and not str(row[2].value).startswith("Ф.И.О"))
    assert titles >= 50
    head = client.get("/api/export/f605/mgmt/2025?pos=head").content
    joined = " ".join(str(c.value) for row in load_workbook(io.BytesIO(head))["НИР студентов"].iter_rows() for c in row if c.value)
    assert "+7 700" not in joined and "•••" in joined


def test_indicator_page_has_29_rows_with_3_manual():
    rows = analytics.indicators("mgmt", 2025)
    assert len(rows) == 29
    assert sum(1 for r in rows if r["source"] == "manual") == 3
    assert sum(1 for r in rows if r["source"] == "staff") == 3


def test_compare_counts_shared_article_once(client):
    data = client.get("/api/analytics/compare", headers=H("director")).json()
    assert len(data["rows"]) == 6
    assert data["total"]["scopus"] == data["summed"]["scopus"] - data["shared"]


def test_supervision_view_and_limits(client):
    head = client.get("/api/analytics/supervision", headers=H("head")).json()
    assert head["linked"] > 20 and head["groups"]
    mine = client.get("/api/analytics/supervision", headers=H("teacher")).json()
    assert len(mine["groups"]) <= 1


def test_mock_import_runs_once_and_is_unconfirmed(client):
    first = client.post("/api/integrations/platonus/import", headers=H("doctoral")).json()
    assert first["added"] == 1
    assert client.post("/api/integrations/platonus/import", headers=H("doctoral")).json()["added"] == 0


def test_limited_agent_answers_and_makes_cards(client):
    answer = client.post("/api/agent/message", data={"session": "t", "text": "Кафедрада Scopus неше?"}, headers=H("head")).json()
    assert answer["mode"] == "limited" and "Scopus: 1" in answer["reply"]
    own = client.post("/api/agent/message", data={"session": "t", "text": "Scopus неше?"}, headers=H("student")).json()
    assert "Scopus: 0" in own["reply"]
    prize = client.post("/api/agent/message", data={"session": "t", "text": "Бішкекте өткен олимпиадада 2 орын алдым"}, headers=H("student")).json()
    assert prize["draft"]["record"]["type"] == "prize" and prize["draft"]["record"]["sections"] == ["3.7"]


def test_audit_endpoint_rejects_wrong_file(client):
    r = client.post("/api/audit/upload", files={"file": ("x.txt", b"hello", "text/plain")}, headers=H("resp"))
    assert r.status_code == 415


class _FakeClaude(BaseHTTPRequestHandler):
    requests: list = []
    script: list = []

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(length))
        type(self).requests.append({"path": self.path, "body": body, "headers": dict(self.headers)})
        payload = type(self).script.pop(0)
        out = self._sse(payload) if body.get("stream") else json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("content-type", "text/event-stream" if body.get("stream") else "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    @staticmethod
    def _sse(payload):
        events = [{"type": "message_start", "message": {**payload, "content": [], "stop_reason": None}}]
        for i, block in enumerate(payload["content"]):
            if block["type"] == "text":
                events.append({"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}})
                events.append({"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": block["text"]}})
            else:
                events.append({"type": "content_block_start", "index": i, "content_block": {**block, "input": {}}})
                events.append({"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}})
            events.append({"type": "content_block_stop", "index": i})
        events.append({"type": "message_delta", "delta": {"stop_reason": payload["stop_reason"], "stop_sequence": None}, "usage": {"output_tokens": 10}})
        events.append({"type": "message_stop"})
        return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()

    def log_message(self, *args):
        pass


def _msg(content, stop):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": content, "stop_reason": stop,
            "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 10}}


def test_ai_path_with_stub_server_uses_tools_and_keeps_pii_out(client, monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _FakeClaude)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("SCIAGENT_AI", "on")
    tool_input = {
        "type": "prize",
        "fields": [{"key": "event", "value": "Инновационная Евразия", "confidence": 0.95, "quote": "Инновационная Евразия", "page": 1},
                   {"key": "award_place", "value": "25.04.2025, 2 место", "confidence": 0.5, "quote": "2 место", "page": 1},
                   {"key": "venue", "value": "Екатеринбург", "confidence": 0.9, "quote": "Екатеринбург", "page": 1}],
        "authors": [store.persons()[next(p["person"] for p in store.kv_get("positions") if p["id"] == "student")]["display_latin"]],
        "attrs": {"index": None, "place": None, "region": "cis", "language": None, "subtype": None, "sdg": [], "coauthor_kz": False, "coauthor_foreign": False, "coauthor_business": False},
    }
    _FakeClaude.requests = []
    _FakeClaude.script = [
        _msg([{"type": "tool_use", "id": "t1", "name": "propose_record", "input": tool_input}], "tool_use"),
        _msg([{"type": "text", "text": "Это раздел 3.7. Проверьте карточку и нажмите «Подтвердить»."}], "end_turn"),
    ]
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    res = client.post("/api/agent/message", data={"session": "s1", "text": "Мой диплом"}, files={"file": ("diploma.png", png, "image/png")}, headers=H("student")).json()
    server.shutdown()
    assert res["mode"] == "ai"
    assert res["draft"]["record"]["sections"] == ["3.7"]
    assert res["draft"]["payload"]["ai"]["confidence"]["award_place"] == 0.5
    assert res["draft"]["payload"]["evidence"][0]["filename"] == "diploma.png"
    first, second = _FakeClaude.requests
    assert first["body"]["model"] == "claude-opus-5-5"
    assert first["body"]["fallbacks"] == "default"
    assert first["body"]["thinking"] == {"type": "adaptive"}
    assert "server-side-fallback-2026-07-01" in first["headers"].get("anthropic-beta", first["headers"].get("Anthropic-Beta", ""))
    assert first["body"]["stream"] is True
    assert all(t.get("strict") is True for t in first["body"]["tools"] if "input_schema" in t)
    assert any(t["name"] == "web_fetch" for t in first["body"]["tools"])
    tool_result = second["body"]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    sent = json.dumps(second["body"], ensure_ascii=False)
    assert "+7 000" not in sent and "@example.edu" not in sent
    assert "3.7" in tool_result["content"]

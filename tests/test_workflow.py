"""Жазбаның толық жолы: автор → ғылыми жетекші → меңгеруші → есеп, және жылдық науқан."""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import tempfile
import threading
from pathlib import Path

os.environ.setdefault("SCIAGENT_DB", str(Path(tempfile.mkdtemp()) / "test.db"))
os.environ.setdefault("SCIAGENT_UPLOADS", str(Path(tempfile.mkdtemp()) / "uploads"))
os.environ["SCIAGENT_AI"] = "off"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from app import agent, analytics, services, store  # noqa: E402
from app.main import app  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ARTICLE = {"type": "article", "attrs": {"index": "koksnvo"}, "fields": {"title": "[Пример] Новая статья для проверки маршрута", "source": "Вестник (пример)", "year": "2025", "issue": "1", "pages": "1-9", "issn": "2345-6787"}}


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


def create(client, pos="student", as_author=False):
    body = {**ARTICLE, "as_author": as_author}
    r = client.post("/api/records", json=body, headers=H(pos)).json()
    return r["record"]["id"]


def in_export(client, title):
    wb = load_workbook(io.BytesIO(client.get("/api/export/f605/mgmt/2025?pos=head").content))
    return any(title in str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value)


def test_full_route_student_supervisor_head_then_report(client):
    before = analytics.overview_for(analytics.active_records())["koksnvo"]
    rid = create(client)
    assert store.record(rid)["status"] == "создано"
    assert not in_export(client, "Новая статья для проверки")

    sent = client.post(f"/api/records/{rid}/submit", json={}, headers=H("student")).json()
    assert sent["status"] == "на согласовании" and sent["stage"] == "У научного руководителя"
    teacher_inbox = client.get("/api/approvals", headers=H("teacher")).json()["items"]
    assert rid in [i["id"] for i in teacher_inbox]
    assert not any(n["text"].startswith("На согласование") and "Новая статья" in n["text"] for n in client.get("/api/notifications", headers=H("master")).json()["items"])
    assert any("Новая статья" in n["text"] for n in client.get("/api/notifications", headers=H("teacher")).json()["items"])

    assert client.post(f"/api/records/{rid}/approve", json={}, headers=H("student")).status_code == 403
    assert client.post(f"/api/records/{rid}/approve", json={}, headers=H("teacher")).json()["stage"] == "У заведующего кафедрой"
    assert not in_export(client, "Новая статья для проверки")
    assert client.post(f"/api/records/{rid}/approve", json={}, headers=H("teacher")).status_code == 403

    done = client.post(f"/api/records/{rid}/approve", json={}, headers=H("head")).json()
    assert done["status"] == "согласовано"
    assert in_export(client, "Новая статья для проверки")
    assert analytics.overview_for(analytics.active_records())["koksnvo"] == before + 1
    assert any("вошла в отчёт" in n["text"] for n in client.get("/api/notifications", headers=H("student")).json()["items"])


def test_teacher_record_skips_supervisor_and_head_record_goes_to_director(client):
    rid = create(client, "teacher")
    assert client.post(f"/api/records/{rid}/submit", json={}, headers=H("teacher")).json()["stage"] == "У заведующего кафедрой"
    store.seed_if_empty(force=True)
    rid = create(client, "head", as_author=True)
    assert client.post(f"/api/records/{rid}/submit", json={}, headers=H("head")).json()["stage"] == "У директора"
    assert client.post(f"/api/records/{rid}/approve", json={}, headers=H("head")).status_code == 403
    assert client.post(f"/api/records/{rid}/approve", json={}, headers=H("director")).json()["status"] == "согласовано"


def test_learner_without_supervisor_must_choose_one(client):
    rid = create(client, "doctoral")
    assert client.get(f"/api/records/{rid}", headers=H("doctoral")).json()["flow"]["needs_supervisor"] is True
    missing = client.post(f"/api/records/{rid}/submit", json={}, headers=H("doctoral"))
    assert missing.status_code == 409 and missing.json()["needs_supervisor"] is True
    teacher = position("teacher")["person"]
    assert client.post(f"/api/records/{rid}/submit", json={"supervisor_id": teacher}, headers=H("doctoral")).json()["stage"] == "У научного руководителя"
    assert client.get(f"/api/records/{rid}", headers=H("teacher")).status_code == 200


def test_return_needs_a_reason_and_author_can_fix_and_resend(client):
    rid = create(client)
    client.post(f"/api/records/{rid}/submit", json={}, headers=H("student"))
    assert client.post(f"/api/records/{rid}/return", json={"note": " "}, headers=H("teacher")).status_code == 422
    assert client.patch(f"/api/records/{rid}", json={"fields": {"pages": "2-9"}}, headers=H("student")).status_code == 403
    assert client.post(f"/api/records/{rid}/return", json={"note": "Уточните страницы"}, headers=H("teacher")).json()["status"] == "на доработке"
    assert client.get(f"/api/records/{rid}", headers=H("student")).json()["flow"]["return_note"] == "Уточните страницы"
    assert client.patch(f"/api/records/{rid}", json={"fields": {"pages": "2-9"}}, headers=H("student")).status_code == 200
    assert client.post(f"/api/records/{rid}/submit", json={}, headers=H("student")).json()["stage"] == "У научного руководителя"


def test_head_can_approve_for_silent_supervisor_and_it_is_recorded(client):
    rid = create(client)
    client.post(f"/api/records/{rid}/submit", json={}, headers=H("student"))
    assert client.post(f"/api/records/{rid}/approve", json={}, headers=H("head")).json()["stage"] == "У заведующего кафедрой"
    history = store.record(rid)["history"]
    assert history[-1]["action"] == "Согласовано за научного руководителя"


def test_approved_record_is_locked_and_reopen_takes_it_out_of_report(client):
    rid = create(client, "teacher")
    client.post(f"/api/records/{rid}/submit", json={}, headers=H("teacher"))
    client.post(f"/api/records/{rid}/approve", json={}, headers=H("head"))
    assert client.patch(f"/api/records/{rid}", json={"fields": {"pages": "2-9"}}, headers=H("teacher")).status_code == 403
    assert in_export(client, "Новая статья для проверки")
    assert client.post(f"/api/records/{rid}/reopen", json={}, headers=H("teacher")).json()["status"] == "создано"
    assert not in_export(client, "Новая статья для проверки")
    assert client.post(f"/api/records/{rid}/reopen", json={}, headers=H("teacher")).status_code == 409


def test_reopen_blocked_after_report_goes_to_signing(client):
    rid = create(client, "teacher")
    client.post(f"/api/records/{rid}/submit", json={}, headers=H("teacher"))
    client.post(f"/api/records/{rid}/approve", json={}, headers=H("head"))
    url = "/api/report/mgmt/2025/transition"
    client.post(url, json={"action": "submit", "force": True}, headers=H("resp"))
    client.post(url, json={"action": "approve"}, headers=H("head"))
    assert client.post(f"/api/records/{rid}/reopen", json={}, headers=H("teacher")).status_code == 409


def test_submit_blocked_when_required_fields_missing(client):
    body = {"type": "article", "attrs": {"index": "koksnvo"}, "fields": {"title": "[Пример] Без журнала"}, "allow_missing": True}
    rid = client.post("/api/records", json=body, headers=H("teacher")).json()["record"]["id"]
    assert client.post(f"/api/records/{rid}/submit", json={}, headers=H("teacher")).status_code == 422


def test_examples_cover_every_stage_and_stay_out_of_the_report(client):
    seed = json.loads((ROOT / "data" / "seed.json").read_text(encoding="utf-8"))
    owner = position("doctoral")["person"]
    examples = [r for r in seed["records"] if r["id"].startswith("e")]
    assert {r["status"] for r in examples} == {"создано", "на доработке", "на согласовании"}
    assert all(r["fields"]["title"].startswith("[Пример]") and r["author_ids"] == [owner] for r in examples)
    data = client.get("/api/report/mgmt/2025", headers=H("head")).json()
    assert len(data["outside"]) == len(examples) and data["rows"] == 164
    assert not in_export(client, "[Пример]")


def test_precheck_splits_clean_from_attention_and_bulk_approves_only_what_is_sent(client):
    items = client.get("/api/approvals", headers=H("head")).json()["items"]
    levels = {i["id"]: i["precheck"]["level"] for i in items}
    assert levels["e004"] == "ok" and levels["e005"] == "warn"
    assert any("скриншот" in r["text"] for i in items if i["id"] == "e005" for r in i["precheck"]["reasons"])
    assert levels["e003"] != "error"
    assert [i["on_behalf"] for i in items if i["id"] == "e003"] == [True]
    r = client.post("/api/approvals/bulk", json={"ids": ["e004", "e001"]}, headers=H("head")).json()
    assert r == {"approved": 1, "skipped": 1}
    assert store.record("e004")["status"] == "согласовано"


def test_author_pipeline_shows_stages_and_attest(client):
    data = client.get("/api/pipeline", headers=H("doctoral")).json()
    assert data["counts"]["создано"] == 1 and data["counts"]["на доработке"] == 1 and data["counts"]["на согласовании"] == 3
    returned = next(i for i in data["items"] if i["status"] == "на доработке")
    assert returned["return_note"] and returned["can_submit"]
    assert data["campaign"]["days_left"] == 21 and data["attested_at"] is None
    client.post("/api/pipeline/attest", headers=H("doctoral"))
    assert client.get("/api/pipeline", headers=H("doctoral")).json()["attested_at"]
    assert client.get("/api/campaign", headers=H("head")).json()["attested"] == 1


def test_reminders_reach_each_group_with_their_own_task(client):
    r = client.post("/api/campaign/remind-all", headers=H("resp")).json()
    assert r["authors"] >= 1 and r["approvers"] == 2 and r["responsible"] == 1
    author = client.get("/api/notifications", headers=H("doctoral")).json()["items"]
    assert any("не отправлено записей: 1" in n["text"] and "возвращено на доработку: 1" in n["text"] for n in author)
    assert any("на вашем согласовании" in n["text"] for n in client.get("/api/notifications", headers=H("head")).json()["items"])
    assert any("проверьте перечень" in n["text"] for n in client.get("/api/notifications", headers=H("resp")).json()["items"])
    assert client.post("/api/campaign/remind-all", headers=H("student")).status_code == 403


def test_automatic_reminder_runs_on_schedule_once_a_day():
    deadline = dt.date.fromisoformat(store.campaign(2025)["deadline"])
    assert services.campaign_tick(deadline - dt.timedelta(days=20)) is None
    first = services.campaign_tick(deadline - dt.timedelta(days=7))
    assert first and first["sent"] > 0
    assert services.campaign_tick(deadline - dt.timedelta(days=7)) is None
    assert services.campaign_tick(deadline - dt.timedelta(days=1))


def test_report_chain_ends_with_science_department(client):
    url = "/api/report/mgmt/2025/transition"
    client.post(url, json={"action": "submit", "force": True}, headers=H("resp"))
    client.post(url, json={"action": "approve"}, headers=H("head"))
    assert client.post(url, json={"action": "return", "note": "x"}, headers=H("science")).status_code == 400
    client.post(url, json={"action": "sign"}, headers=H("director"))
    assert client.post(url, json={"action": "return", "note": "x"}, headers=H("head")).status_code == 400
    assert client.post(url, json={"action": "accept"}, headers=H("director")).status_code == 400
    assert client.post(url, json={"action": "accept"}, headers=H("science")).json()["status"] == "принято"
    assert "принято" in {u["status"] for u in client.get("/api/campaign", headers=H("science")).json()["units"]}


def test_narrative_uses_real_figures(client):
    text = client.get("/api/report/mgmt/2025/narrative", headers=H("head")).json()
    assert text["mode"] == "rules" and "164" in text["text"] and "Снизилось" in text["text"]
    assert client.get("/api/report/mgmt/2025/narrative", headers=H("student")).status_code == 403


def test_agent_answers_about_the_process(client):
    def ask(text, pos):
        return client.post("/api/agent/message", data={"session": "w", "text": text}, headers=H(pos)).json()["reply"]

    assert "Мои результаты" in ask("Как внести статью?", "doctoral")
    assert "Уточните страницы" in ask("Где сейчас мои записи?", "doctoral")
    assert "Ждут решения: 3" in ask("Что на моём согласовании?", "head")
    assert "Согласовать записи: 3" in ask("Что мне нужно сделать?", "head")
    assert "Ещё не согласовано и в отчёт не вошло: 5" in ask("Что мешает сдать отчёт?", "head")


def test_student_reposting_teachers_article_changes_nothing_and_sees_nothing(client):
    target = next(r for r in store.records(unit="mgmt", year=2025, approved_only=True) if r["type"] == "article" and position("student")["person"] not in r["author_ids"] and r["attrs"].get("index") == "scopus")
    before = json.dumps(store.record(target["id"])["author_ids"])
    r = client.post("/api/records", json={"type": "article", "attrs": {"index": "scopus"}, "fields": {"title": target["fields"]["title"], "pages": "99-100"}, "allow_missing": True}, headers=H("student")).json()
    assert r["merged"] is True and r["claimed"] is True and "fields" not in r["record"]
    after = store.record(target["id"])
    assert json.dumps(after["author_ids"]) == before and after["fields"].get("pages") == target["fields"].get("pages")
    me = position("student")["person"]
    assert after["claims"] == [me]
    assert client.get(f"/api/records/{target['id']}", headers=H("student")).status_code == 403
    assert any("указывает себя соавтором" in n["text"] for n in client.get("/api/notifications", headers=H("resp")).json()["items"])
    flow = client.get(f"/api/records/{target['id']}", headers=H("resp")).json()["flow"]
    assert flow["claims"][0]["id"] == me
    assert client.post(f"/api/records/{target['id']}/claim", json={"person": me, "accept": True}, headers=H("student")).status_code == 403
    assert client.post(f"/api/records/{target['id']}/claim", json={"person": me, "accept": True}, headers=H("resp")).status_code == 200
    assert me in store.record(target["id"])["author_ids"]


def test_head_cannot_approve_a_record_they_coauthored(client):
    head = position("head")["person"]
    body = {**ARTICLE, "author_ids": [head]}
    rid = client.post("/api/records", json=body, headers=H("teacher")).json()["record"]["id"]
    assert client.post(f"/api/records/{rid}/submit", json={}, headers=H("teacher")).json()["stage"] == "У директора"
    assert client.post(f"/api/records/{rid}/approve", json={}, headers=H("head")).status_code == 403
    assert client.post(f"/api/records/{rid}/approve", json={}, headers=H("director")).json()["status"] == "согласовано"


def test_route_follows_the_author_not_who_typed_it(client):
    learner = position("student")["person"]
    rid = client.post("/api/records", json={**ARTICLE, "author_ids": [learner]}, headers=H("resp")).json()["record"]["id"]
    assert client.post(f"/api/records/{rid}/submit", json={}, headers=H("resp")).json()["stage"] == "У научного руководителя"
    store.seed_if_empty(force=True)
    teacher = position("teacher")["person"]
    rid = client.post("/api/records", json={**ARTICLE, "author_ids": [teacher]}, headers=H("head")).json()["record"]["id"]
    assert client.post(f"/api/records/{rid}/submit", json={}, headers=H("head")).json()["stage"] == "У заведующего кафедрой"


def test_supervisor_choice_is_validated(client):
    rid = create(client, "doctoral")
    other_learner = position("master")["person"]
    assert client.post(f"/api/records/{rid}/submit", json={"supervisor_id": other_learner}, headers=H("doctoral")).status_code == 409
    assert client.post(f"/api/records/{rid}/submit", json={"supervisor_id": "нет"}, headers=H("doctoral")).status_code == 409
    store.seed_if_empty(force=True)
    rid = create(client, "student")
    assert client.post(f"/api/records/{rid}/submit", json={"supervisor_id": position("resp")["person"]}, headers=H("student")).status_code == 200
    assert store.record(rid)["route"][0]["person"] == position("teacher")["person"]


def test_saving_masked_contacts_keeps_real_values(client):
    prize = next(r for r in store.records(unit="mgmt", year=2025) if r["type"] == "prize" and r["fields"].get("phone"))
    real = prize["fields"]["phone"]
    shown = client.get(f"/api/records/{prize['id']}", headers=H("head")).json()["record"]["fields"]
    assert shown["phone"] == "•••"
    assert client.patch(f"/api/records/{prize['id']}", json={"fields": shown}, headers=H("head")).status_code == 200
    assert store.record(prize["id"])["fields"]["phone"] == real


def test_evidence_path_from_client_is_rejected(client):
    for stored in ("..\\sciagent.db", "../sciagent.db", str(store.DB_PATH), "abc.pdf"):
        rid = client.post("/api/records", json={**ARTICLE, "fields": {**ARTICLE["fields"], "title": f"[Пример] Проверка пути {stored[:6]}"}, "evidence": [{"filename": "x.pdf", "stored": stored}]}, headers=H("student")).json()["record"]["id"]
        assert store.record(rid)["evidence"] == []
    assert store.upload_path("..\\sciagent.db") is None
    assert client.get(f"/api/records/{rid}/evidence/..%5Csciagent.db?pos=student").status_code == 404


def test_locked_report_blocks_changes_and_excel_stays_signed(client):
    url = "/api/report/mgmt/2025/transition"
    prize = next(r for r in store.records(unit="mgmt", year=2025) if r["type"] == "prize" and r["fields"].get("event"))
    client.post(url, json={"action": "submit", "force": True}, headers=H("resp"))
    client.post(url, json={"action": "approve"}, headers=H("head"))
    assert client.patch(f"/api/records/{prize['id']}", json={"fields": {"venue": "x"}}, headers=H("head")).status_code == 409
    assert client.put("/api/report/mgmt/2025/manual", json={"funding": 1}, headers=H("resp")).status_code == 409
    assert client.post("/api/records/e004/approve", json={}, headers=H("head")).status_code == 409
    client.post(url, json={"action": "sign"}, headers=H("director"))
    signed = load_workbook(io.BytesIO(client.get("/api/export/f605/mgmt/2025?pos=head").content))
    client.post("/api/records/e004/approve", json={}, headers=H("head"))
    assert store.record("e004")["status"] == "согласовано"
    assert any("следующей версии" in n["text"] for n in client.get("/api/notifications", headers=H("doctoral")).json()["items"])
    after = load_workbook(io.BytesIO(client.get("/api/export/f605/mgmt/2025?pos=head").content))
    assert [c.value for c in signed["НИР докторантов"]["D"]] == [c.value for c in after["НИР докторантов"]["D"]]


def test_own_approved_record_cannot_be_edited_even_by_head(client):
    rid = create(client, "head", as_author=True)
    client.post(f"/api/records/{rid}/submit", json={}, headers=H("head"))
    client.post(f"/api/records/{rid}/approve", json={}, headers=H("director"))
    assert client.patch(f"/api/records/{rid}", json={"fields": {"pages": "2-3"}}, headers=H("head")).status_code == 403


def test_manager_edit_of_approved_record_is_in_history(client):
    rec = next(r for r in store.records(unit="mgmt", year=2025, approved_only=True) if position("resp")["person"] not in r["author_ids"] and r["type"] == "article")
    client.patch(f"/api/records/{rec['id']}", json={"fields": {"issue": "77"}}, headers=H("resp"))
    assert store.record(rec["id"])["history"][-1]["action"] == "Данные согласованной записи изменены"


def test_changing_year_moves_record_to_that_year(client):
    rid = create(client, "teacher")
    client.patch(f"/api/records/{rid}", json={"fields": {"year": "2024"}}, headers=H("teacher"))
    assert store.record(rid)["year"] == 2024
    mono = client.post("/api/records", json={"type": "monograph", "year": 2024, "attrs": {"place": "kz", "language": "ru"}, "fields": {"title": "[Пример] Монография прошлого года", "publisher": "Издательство", "city": "Астана", "sheets": "5", "isbn": "978-601-7625-79-5"}}, headers=H("teacher")).json()
    assert store.record(mono["record"]["id"])["year"] == 2024


def test_record_without_a_form_section_cannot_be_sent(client):
    r = client.post("/api/records", json={"type": "prize", "attrs": {"region": "kz"}, "fields": {"event": "[Пример] Конкурс", "award_place": "1 место", "venue": "Астана"}, "allow_missing": True}, headers=H("teacher")).json()
    rid = r["record"]["id"]
    assert not store.record(rid)["sections"]
    res = client.post(f"/api/records/{rid}/submit", json={}, headers=H("teacher"))
    assert res.status_code == 422 and "Раздел отчёта не определён" in res.json()["detail"]


def test_endpoints_check_who_is_asking(client):
    assert client.post("/api/demo/reset", headers=H("student")).status_code == 403
    assert client.post("/api/integrations/platonus/import", headers=H("student")).json()["added"] == 0
    assert not any(r.get("source") == "platonus" for r in store.records())
    owner_cand = store.candidates(person=position("doctoral")["person"])[0]
    assert client.post(f"/api/candidates/{owner_cand['id']}/decide", json={"mine": True}, headers=H("student")).status_code == 404
    assert client.post(f"/api/candidates/{owner_cand['id']}/decide", json={"mine": True}, headers=H("doctoral")).status_code == 200


def test_audit_import_goes_to_head_for_approval(client):
    from app import audit, reporting

    path = Path(tempfile.mkdtemp()) / "old.xlsx"
    path.write_bytes(reporting.f605_bytes(services.snapshot("mgmt", 2025), pii=True))
    for rec in store.records(unit="mgmt", year=2025, approved_only=True):
        if rec["type"] == "article" and rec["attrs"].get("index") == "scopus":
            title = rec["fields"]["title"]
            rec["merged_into"] = "x"
            rec["fields"]["title"] = "удалено"
            store.save_record(rec)
            break
    before = analytics.overview("mgmt", 2025)["raw"]
    result = audit.import_rows(path, position("resp"))
    assert result["added"] >= 1
    new = next(r for r in store.records(unit="mgmt", year=2025) if r["fields"].get("title") == title)
    assert new["status"] == "на согласовании" and "phone" not in new["fields"] and new["fields"]["authors_text"]
    assert analytics.overview("mgmt", 2025)["raw"] == before


def test_assistant_without_key_answers_common_manager_questions(client):
    def ask(text, pos):
        return client.post("/api/agent/message", data={"session": "q", "text": text}, headers=H(pos)).json()

    chart = ask("Покажи публикации кафедры диаграммой", "head")
    assert chart["charts"] and "доступна" not in chart["reply"]
    assert "Ждут решения" in ask("Что мне согласовать?", "head")["reply"]
    assert "Ещё не отправили" in ask("Кто ещё не отправил список?", "head")["reply"]
    assert "Ещё не отправили" not in ask("Кто ещё не отправил список?", "student")["reply"]
    assert ask("Кто из моих обучающихся опубликовался?", "teacher")["charts"]


def test_importing_the_same_report_adds_no_untitled_rows():
    from app import audit

    result = audit.import_rows(ROOT / "static" / "samples" / "5_audit_uchin_esep.xlsx", position("resp"))
    assert result["added"] == 0
    assert not any(services.display_title(r) == "(без названия)" for r in store.records(unit="mgmt", year=2025))


def test_agent_counts_match_analytics(client):
    head = agent.stats_for("overview", position("head"))
    raw = analytics.overview("mgmt", 2025)["raw"]
    assert head["scopus"] == raw["scopus"] and head["koksnvo"] == raw["koksnvo"] and head["not_yet_approved"] == 5


def test_campaign_numbers_agree_and_owner_can_confirm(client):
    camp = client.get("/api/campaign", headers=H("head")).json()
    mgmt = next(u for u in camp["units"] if u["id"] == "mgmt")
    assert mgmt["done"] == camp["funnel"]["approved"] == 164
    pending = next(i for i in client.get("/api/pipeline", headers=H("doctoral")).json()["items"] if i["needs_confirm"])
    assert client.post(f"/api/records/{pending['id']}/confirm", headers=H("doctoral")).status_code == 200
    assert store.record(pending["id"])["confirmed"] is True


def test_reminder_about_heads_own_record_goes_to_director(client):
    rid = create(client, "head", as_author=True)
    client.post(f"/api/records/{rid}/submit", json={}, headers=H("head"))
    client.post("/api/campaign/remind-all", headers=H("resp"))
    assert any("на вашем согласовании записей: 1" in n["text"] for n in client.get("/api/notifications", headers=H("director")).json()["items"])


def test_incomplete_draft_can_be_saved_from_form(client):
    r = client.post("/api/records", json={"type": "article", "attrs": {}, "fields": {"title": "[Пример] Неполный черновик"}, "allow_missing": True}, headers=H("student"))
    assert r.status_code == 200 and store.record(r.json()["record"]["id"])["status"] == "создано"


def test_supervisor_sees_only_own_figures(client):
    data = client.get("/api/analytics/supervision", headers=H("teacher")).json()
    assert data["missing"] == [] and data["linked"] == 8


def test_parallel_requests_do_not_break_the_database(client):
    errors = []

    def worker(pos):
        try:
            for _ in range(15):
                assert client.get("/api/bootstrap", headers=H(pos)).status_code == 200
                assert client.get("/api/pipeline", headers=H(pos)).status_code == 200
                store.notify("проверка", role="head", unit="mgmt")
        except Exception as exc:  # тест кез келген қатені жинайды
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(p,)) for p in ("head", "doctoral", "teacher", "student", "resp", "director")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_queue_summary_sends_no_author_names_to_the_model():
    data = agent.queue_summary(position("head"))
    owner = store.persons()[position("doctoral")["person"]]["display_name"]
    assert owner not in json.dumps(data, ensure_ascii=False)

"""SciAgent.ENU API. Деректі өзгертетін әрекет рөлмен тексеріледі және журналға жазылады."""
from __future__ import annotations

import base64
import json
import os
import queue
import secrets
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import agent, analytics, audit, integrations, reporting, services, store, validators
from .catalog import AWARD_SUBTYPES, INDEX_LABELS, LANGUAGE_LABELS, PLACE_LABELS, REGION_LABELS, ROLE_LABELS, TYPES, WORK_RECORD_TYPES, WORK_TYPES, display_title, work_form, work_type_label, work_type_of

ROOT = Path(__file__).resolve().parent.parent


def _reminder_loop() -> None:
    """Мерзімге қарай еске салуды күніне бір рет тексереді."""
    while True:
        try:
            services.campaign_tick()
        except Exception as exc:  # фондағы тексеру серверді тоқтатпауы керек
            print(f"campaign_tick: {exc.__class__.__name__}")
        time.sleep(6 * 60 * 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.seed_if_empty()
    threading.Thread(target=_reminder_loop, daemon=True).start()
    yield


app = FastAPI(title="SciAgent.ENU API", version="0.1.0", lifespan=lifespan,
              description="API научной отчётности для модуля «Научная деятельность» Smart.ENU. Демо-версия, условные данные.")

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MANAGERS = ("responsible", "head", "director", "science")


@app.middleware("http")
async def demo_password(request: Request, call_next):
    """Демода логин жоқ. Сілтеме интернетке шыққанда SCIAGENT_DEMO_PASSWORD кіруді шектейді."""
    secret = os.environ.get("SCIAGENT_DEMO_PASSWORD")
    if secret and request.url.path != "/healthz":
        supplied = ""
        header = request.headers.get("authorization", "")
        if header.lower().startswith("basic "):
            try:
                supplied = base64.b64decode(header[6:]).decode("utf-8").split(":", 1)[1]
            except (ValueError, IndexError):
                supplied = ""
        if not secrets.compare_digest(supplied.encode("utf-8"), secret.encode("utf-8")):
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="SciAgent.ENU demo"'})
    return await call_next(request)


def position_of(pos: str | None) -> dict:
    positions = {p["id"]: p for p in store.kv_get("positions", [])}
    return positions.get(pos or "head") or positions["head"]


def require(position: dict, *roles: str) -> None:
    if position.get("role") not in roles:
        raise HTTPException(403, "У вас нет прав на это действие")


def check_unit(position: dict, unit: str) -> None:
    allowed = services.scope_units(position)
    if allowed is not None and unit not in allowed:
        raise HTTPException(403, "Это подразделение не входит в вашу зону доступа")


def guard_report_open(unit: str, year: int) -> None:
    if services.report_locked(unit, year):
        raise HTTPException(409, "Отчёт уже на подписании или утверждён. Чтобы внести изменения, его нужно вернуть на доработку.")


def default_unit(position: dict) -> str:
    return position["unit"] if store.units().get(position["unit"], {}).get("kind") == "department" else "mgmt"


def card(rec: dict, position: dict, persons: dict) -> dict:
    masked = services.mask_record(rec, position)
    names = [persons[a]["display_name"] for a in rec.get("author_ids", []) if a in persons] + rec.get("external_authors", [])
    return {"id": rec["id"], "type": rec["type"], "type_label": TYPES[rec["type"]]["label"], "title": display_title(rec), "year": rec["year"],
            "authors": names, "sections": rec.get("sections", []), "status": rec.get("status"), "confirmed": rec.get("confirmed", False),
            "in_press": rec.get("in_press", False), "source": rec.get("source"), "source_text": masked["fields"].get("source", ""), "unit": rec["unit"],
            "index": rec["attrs"].get("index"), "has_evidence": bool(rec.get("evidence")), "stage": services.stage_text(rec)}


@app.get("/healthz", include_in_schema=False)
def healthz():
    """Хостинг тексеретін бет: дерек ашпайды, сондықтан құпия сөзсіз жауап береді."""
    return {"status": "ok"}


@app.get("/api/bootstrap")
def bootstrap(x_position: str | None = Header(None)):
    position = position_of(x_position)
    persons = store.persons()
    me = persons.get(position["person"], {})
    # Демо иесінен басқа лауазымдар рөлмен көрсетіледі: әрекет нақты адамның атынан жасалғандай көрінбеуі керек.
    shown_name = me.get("display_name") if position.get("show_name") else None
    return {
        "position": position, "person": {"name": shown_name, "role": me.get("role"), "group": me.get("group") if shown_name else ""},
        "positions": store.kv_get("positions", []), "types": TYPES,
        "work_types": {k: work_form(k) for k in WORK_TYPES}, "work_record_types": WORK_RECORD_TYPES,
        "labels": {"index": INDEX_LABELS, "place": PLACE_LABELS, "region": REGION_LABELS, "language": LANGUAGE_LABELS, "subtype": AWARD_SUBTYPES, "role": ROLE_LABELS},
        "ai": {"available": agent.ai_available(), "model": agent.MODEL if agent.ai_available() else None},
        "unread": sum(1 for n in store.notifications(position) if not n["read"]),
        "inbox": len(services.inbox(position)),
        "default_unit": default_unit(position), "year": 2025,
    }


@app.get("/api/home")
def home(x_position: str | None = Header(None)):
    position = position_of(x_position)
    role = position["role"]
    tasks = []
    me = position["person"]
    mine = services.visible_records(position, mine_only=True)
    pending = [r for r in mine if me in services.awaiting_confirmation(r)]
    waiting = services.inbox(position)
    if waiting:
        clean = sum(1 for w in waiting if w["precheck"]["level"] == "ok")
        tasks.append({"icon": "fa-stamp", "title": "На вашем согласовании", "text": f"Записей ждут решения: {len(waiting)}, без замечаний: {clean}", "count": len(waiting), "link": "approvals"})
    if pending:
        tasks.append({"icon": "fa-circle-check", "title": "Записи, ожидающие подтверждения", "text": f"Записей ожидают вашего подтверждения: {len(pending)}", "count": len(pending), "link": "records"})
    cand = store.candidates(person=me)
    if cand:
        tasks.append({"icon": "fa-magnifying-glass", "title": "Найденные публикации", "text": "Система нашла публикации, которые могут быть вашими", "count": len(cand), "link": "found"})
    press = [r for r in mine if r.get("in_press")]
    if press:
        tasks.append({"icon": "fa-hourglass-half", "title": "Записи в печати", "text": "Проверьте выход и обновите страницы", "count": len(press), "link": "inpress"})
    if role in ("responsible", "head"):
        q = services.review_queue()
        tasks.append({"icon": "fa-list-check", "title": "Очередь проверки", "text": f"Из {q['total']} записей {q['auto_ok']} прошли автоматически, остальные нужно посмотреть", "count": len(q["items"]), "link": "review"})
        tasks.append({"icon": "fa-clone", "title": "Повторяющиеся записи", "text": "Группы, где одна статья записана несколько раз", "count": sum(1 for d in q["duplicates"] if d["kind"] != "similar"), "link": "review"})
    if role in ("responsible", "head", "director"):
        state = store.report_state("mgmt", 2025)
        tasks.append({"icon": "fa-file-excel", "title": "Отчёт НИР за 2025 год", "text": f"Кафедра «Менеджмент», статус: {state['status']}", "count": None, "link": "report"})
    if role in ("director", "science"):
        status = services.campaign_status(2025)
        done = sum(1 for u in status["units"] if u["status"] in ("согласовано", "принято"))
        tasks.append({"icon": "fa-flag-checkered", "title": "Кампания отчётности", "text": f"Отчёт утвердили кафедр: {done} из 6. Срок: {(status['campaign'] or {}).get('deadline', '')}", "count": None, "link": "campaign"})
    if role == "supervisor":
        data = analytics.supervision_table("mgmt", 2025, supervisor=me)
        n = sum(g["count"] for g in data["groups"])
        tasks.append({"icon": "fa-user-graduate", "title": "Мои обучающиеся", "text": "Их публикации и призовые места в одном месте", "count": n, "link": "supervision"})
    return {"tasks": tasks, "notifications": store.notifications(position, 6)}


@app.get("/api/works")
def list_works(mine: bool = True, x_position: str | None = Header(None)):
    """Smart.ENU «Научные работы»: жарияланымның бірыңғай тізімі. Модуль жазбаны осы тізімнен алады."""
    position = position_of(x_position)
    persons = store.persons()
    rows = [r for r in services.visible_records(position, mine_only=mine, with_works=True) if work_type_of(r)]
    rows.sort(key=lambda r: (-r["year"], display_title(r)))
    items = [{"id": r["id"], "title": display_title(r), "work_type_label": work_type_label(r), "year": r["year"], "status": r.get("status"), "source": r.get("source"),
              "authors": [persons[a]["display_name"] for a in r.get("author_ids", []) if a in persons] + r.get("external_authors", [])} for r in rows]
    return {"items": items, "total": len(items)}


@app.post("/api/works")
def add_work(body: dict = Body(...), x_position: str | None = Header(None)):
    """«Добавить научную работу». Есепке керек қалған белгіні автор модульде толтырады, сондықтан бұл жерде екі өріс қана міндетті."""
    position = position_of(x_position)
    key = body.get("work_type")
    spec = WORK_TYPES.get(key)
    if not spec:
        raise HTTPException(422, "Выберите тип научной работы")
    fields = {k: str(v).strip() for k, v in (body.get("fields") or {}).items() if str(v or "").strip()}
    if not fields.get("title") or not fields.get("year"):
        raise HTTPException(422, "Укажите название и год")
    return services.create_record({"type": spec["type"], "attrs": dict(spec["attrs"]), "fields": fields, "work_type": key, "as_author": True,
                                   "author_ids": body.get("author_ids") or [], "external_authors": body.get("external_authors") or []}, position, "smartenu")


@app.get("/api/records")
def list_records(x_position: str | None = Header(None), q: str = "", type: str = "", status: str = "", section: str = "", year: int | None = None,
                 mine: bool = False, confirmed: str = ""):
    position = position_of(x_position)
    rows = services.visible_records(position, year=year, mine_only=mine)
    persons = store.persons()
    out = []
    low = q.lower()
    for r in rows:
        if type and r["type"] != type:
            continue
        if section and section not in r.get("sections", []):
            continue
        if confirmed and str(bool(r.get("confirmed"))).lower() != confirmed:
            continue
        c = card(r, position, persons)
        if low and low not in (c["title"] + " " + " ".join(c["authors"])).lower():
            continue
        out.append(c)
    return {"items": out, "total": len(out)}


@app.get("/api/records/{rid}")
def get_record(rid: str, x_position: str | None = Header(None)):
    position = position_of(x_position)
    rec = store.record(rid)
    if not rec:
        raise HTTPException(404, "Запись не найдена")
    if not services.can_see(position, rec):
        raise HTTPException(403, "Эта запись не входит в вашу зону доступа")
    persons = store.persons()
    coll = services.record_issues(store.records(unit=rec["unit"], year=rec["year"]))
    issues = [i for i in coll.get(rec["id"], validators.check_record(rec)) if i["code"] not in rec.get("dismissed", [])]
    masked = services.mask_record(rec, position)
    if rec["type"] == "prize" and services.pii_allowed(position):
        store.log(position, "Открыты контактные данные", rid)
    authors = [{"id": a, "name": persons[a]["display_name"], "latin": persons[a]["display_latin"], "role": persons[a]["role"]}
               for a in rec.get("author_ids", []) if a in persons]
    supervisors = [{"id": s, "name": persons[s]["display_name"]} for s in rec.get("supervisor_ids", []) if s in persons]
    needs = sorted({reporting.evidence_need(s) for s in rec.get("sections", [])} - {None})
    return {"record": masked, "title": display_title(rec), "issues": issues, "authors": authors, "supervisors": supervisors, "fixes": services.FIXES,
            "can_edit": services.can_edit(position, rec), "evidence_needed": needs, "smartenu": integrations.smartenu_payload(rec),
            "flow": services.flow_view(rec, position)}


def _flow_result(result: dict) -> dict:
    if result.get("error"):
        if result.get("needs_supervisor"):
            return JSONResponse({"detail": result["error"], "needs_supervisor": True}, status_code=409)
        raise HTTPException(result.get("code", 400), result["error"])
    return {"stage": result["stage"], "status": result["record"]["status"]}


@app.post("/api/records/{rid}/submit")
def submit_record(rid: str, body: dict = Body(default={}), x_position: str | None = Header(None)):
    return _flow_result(services.submit_record(rid, position_of(x_position), body.get("supervisor_id"), body.get("note", "")))


@app.post("/api/records/{rid}/approve")
def approve_record(rid: str, body: dict = Body(default={}), x_position: str | None = Header(None)):
    return _flow_result(services.approve_record(rid, position_of(x_position), body.get("note", "")))


@app.post("/api/records/{rid}/return")
def return_record(rid: str, body: dict = Body(default={}), x_position: str | None = Header(None)):
    return _flow_result(services.return_record(rid, position_of(x_position), body.get("note", "")))


@app.post("/api/records/{rid}/reopen")
def reopen_record(rid: str, body: dict = Body(default={}), x_position: str | None = Header(None)):
    return _flow_result(services.reopen_record(rid, position_of(x_position), body.get("note", "")))


@app.post("/api/records/{rid}/claim")
def resolve_claim(rid: str, body: dict = Body(...), x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, "responsible", "head")
    rec = store.record(rid)
    if rec:
        check_unit(position, rec["unit"])
        guard_report_open(rec["unit"], rec["year"])
    return _flow_result(services.resolve_claim(rid, body.get("person", ""), bool(body.get("accept")), position))


@app.get("/api/pipeline")
def my_pipeline(x_position: str | None = Header(None)):
    return services.pipeline(position_of(x_position))


@app.post("/api/pipeline/attest")
def attest(x_position: str | None = Header(None)):
    return services.attest_list(position_of(x_position))


@app.get("/api/approvals")
def approvals(x_position: str | None = Header(None)):
    return {"items": services.inbox(position_of(x_position))}


@app.post("/api/approvals/bulk")
def approvals_bulk(body: dict = Body(...), x_position: str | None = Header(None)):
    return services.approve_many(body.get("ids", []), position_of(x_position))


@app.post("/api/records/preview")
def preview_record(payload: dict = Body(...), x_position: str | None = Header(None)):
    return services.preview(payload, position_of(x_position))


@app.post("/api/records")
def create_record(payload: dict = Body(...), x_position: str | None = Header(None)):
    position = position_of(x_position)
    view = services.preview(payload, position)
    if view["missing"] and not payload.get("allow_missing"):
        raise HTTPException(422, {"message": "Не заполнены обязательные поля", "missing": view["missing"]})
    return services.create_record(payload, position, payload.get("source", "form"))


@app.patch("/api/records/{rid}")
def patch_record(rid: str, patch: dict = Body(...), x_position: str | None = Header(None)):
    position = position_of(x_position)
    rec = store.record(rid)
    if not rec:
        raise HTTPException(404, "Запись не найдена")
    if not services.can_edit(position, rec):
        raise HTTPException(403, "У вас нет прав изменять эту запись")
    if rec.get("status") == store.APPROVED:
        guard_report_open(rec["unit"], rec["year"])
    return {"record": services.mask_record(services.update_record(rid, patch, position), position)}


@app.post("/api/records/{rid}/confirm")
def confirm_record(rid: str, x_position: str | None = Header(None)):
    position = position_of(x_position)
    rec = store.record(rid)
    if not rec:
        raise HTTPException(404, "Запись не найдена")
    if not (services.is_author(position, rec) or services.can_edit(position, rec)):
        raise HTTPException(403, "У вас нет прав подтверждать эту запись")
    rec["confirmed"] = True
    rec.setdefault("confirmed_by", []).append(position["person"])
    store.save_record(rec)
    store.log(position, "Запись подтверждена", rid, display_title(rec)[:80])
    return {"ok": True}


@app.post("/api/records/{rid}/fix")
def fix(rid: str, code: str = Body(..., embed=True), x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, "responsible", "head")
    current = store.record(rid)
    if current and current.get("status") == store.APPROVED:
        guard_report_open(current["unit"], current["year"])
    rec = services.fix_issue(rid, code, position)
    if not rec:
        raise HTTPException(404, "Запись не найдена")
    return {"record": services.mask_record(rec, position)}


@app.post("/api/records/{rid}/dismiss")
def dismiss(rid: str, code: str = Body(..., embed=True), x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, "responsible", "head")
    current = store.record(rid)
    if current and current.get("status") == store.APPROVED:
        guard_report_open(current["unit"], current["year"])
    rec = services.dismiss_issue(rid, code, position)
    if not rec:
        raise HTTPException(404, "Запись не найдена")
    return {"ok": True}


@app.post("/api/records/{rid}/evidence")
async def add_evidence(rid: str, file: UploadFile = File(...), x_position: str | None = Header(None)):
    position = position_of(x_position)
    rec = store.record(rid)
    if not rec:
        raise HTTPException(404, "Запись не найдена")
    if not services.can_edit(position, rec):
        raise HTTPException(403, "Нет прав")
    data = await file.read()
    if len(data) > agent.MAX_FILE_BYTES:
        raise HTTPException(413, "Файл слишком большой")
    if Path(file.filename or "").suffix.lower() not in (".pdf", ".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(415, "Загрузите PDF или изображение")
    item = agent._save_upload(file.filename, data)
    rec.setdefault("evidence", []).append(item)
    store.save_record(rec)
    store.log(position, "Добавлен подтверждающий документ", rid, item["filename"])
    return {"evidence": rec["evidence"]}


@app.get("/api/records/{rid}/evidence/{stored}")
def get_evidence(rid: str, stored: str, pos: str | None = Query(None)):
    position = position_of(pos)
    rec = store.record(rid)
    if not rec or not services.can_see(position, rec):
        raise HTTPException(403, "Нет прав")
    item = next((e for e in rec.get("evidence", []) if e["stored"] == stored), None)
    path = store.upload_path(stored) if item else None
    if not path:
        raise HTTPException(404, "Файл не найден")
    return FileResponse(path, filename=item["filename"])


@app.get("/api/directory")
def directory(q: str = "", x_position: str | None = Header(None)):
    position_of(x_position)
    low = q.lower()
    out = []
    for p in store.persons().values():
        if p["role"] == "manager":
            continue
        if low and low not in p["display_name"].lower() and low not in p["display_latin"].lower():
            continue
        out.append({"id": p["id"], "name": p["display_name"], "role": p["role"], "group": p.get("group", "")})
    return {"items": out[:30]}


@app.get("/api/review")
def review(x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, "responsible", "head")
    data = services.review_queue(position["unit"], 2025)
    data["labels"] = audit.ISSUE_LABELS
    return data


@app.post("/api/review/dismiss-code")
def review_dismiss_code(code: str = Body(..., embed=True), x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, "responsible", "head")
    return {"dismissed": services.dismiss_code(code, position["unit"], 2025, position)}


@app.post("/api/duplicates/merge")
def merge(body: dict = Body(...), x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, "responsible", "head")
    guard_report_open(position["unit"], 2025)
    result = services.merge_duplicates(body.get("record_ids", []), body.get("primary"), position)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return {"merged": result["merged"], "id": result["record"]["id"], "sections": result["record"]["sections"]}


@app.post("/api/duplicates/merge-all")
def merge_all(x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, "responsible", "head")
    guard_report_open(position["unit"], 2025)
    groups = services.duplicates(store.records(unit=position["unit"], year=2025, approved_only=True))
    merged = 0
    for g in groups:
        if g["kind"] in ("exact", "cross_section", "cross_role", "conflict"):
            merged += services.merge_duplicates(g["record_ids"], None, position).get("merged", 0)
    return {"merged": merged}


@app.get("/api/candidates")
def candidates(x_position: str | None = Header(None)):
    position = position_of(x_position)
    return {"items": store.candidates(person=position["person"])}


@app.post("/api/candidates/search")
def search_candidates(body: dict = Body(...), x_position: str | None = Header(None)):
    """ORCID бойынша Crossref пен OpenAlex-тен нақты іздейді. Базада бар жарияланымдар шығарылмайды."""
    position = position_of(x_position)
    orcid = integrations.find_orcid(body.get("orcid", ""))
    if not orcid:
        raise HTTPException(400, "ORCID должен быть в формате 0000-0000-0000-0000")
    works = integrations.crossref_by_orcid(orcid) + integrations.openalex_by_orcid(orcid)
    added, already = 0, 0
    seen = set()
    existing_titles = {services.norm_title(c.get("title", "")) for c in store.candidates(person=position["person"], status=None)}
    for w in works:
        fields = w["fields"]
        key = services.norm_title(fields.get("title", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        if services.find_existing(fields) or key in existing_titles:
            already += 1
            continue
        hint = integrations.index_hint(fields.get("issn", ""), fields.get("source", ""))
        store.add_candidate({"person": position["person"], "title": fields.get("title", ""), "journal": fields.get("source", ""), "year": int(fields.get("year") or 2025),
                             "doi": fields.get("doi", ""), "issn": fields.get("issn", ""), "pages": fields.get("pages", ""), "source": w["verified_by"], "index": (hint or {}).get("index", ""),
                             "authors": w.get("authors", []), "type": w.get("type", "article"), "issue": fields.get("issue", "")})
        added += 1
    store.log(position, "Поиск по ORCID", "", f"найдено {len(works)}, новых {added}")
    return {"found": len(works), "added": added, "already": already, "network_ok": bool(works)}


@app.post("/api/candidates/{cid}/decide")
def decide_candidate(cid: str, body: dict = Body(...), x_position: str | None = Header(None)):
    position = position_of(x_position)
    mine = bool(body.get("mine"))
    if not any(c["id"] == cid for c in store.candidates(person=position["person"])):
        raise HTTPException(404, "Не найдено")
    doc = store.set_candidate_status(cid, "mine" if mine else "not_mine")
    if not doc:
        raise HTTPException(404, "Не найдено")
    if not mine:
        store.log(position, "Публикация отмечена как «не моя»", cid)
        return {"ok": True}
    attrs = {"index": doc["index"]} if doc.get("index") else {}
    fields = {"title": doc["title"], "source": doc.get("journal", ""), "year": str(doc.get("year", "")), "pages": doc.get("pages", ""), "issn": doc.get("issn", ""),
              "doi": doc.get("doi", ""), "issue": doc.get("issue", "")}
    payload = {"type": doc.get("type", "article"), "fields": fields, "attrs": attrs, "authors": doc.get("authors", []), "ai": {"mode": "harvest", "verified_by": doc.get("source")}}
    result = services.create_record(payload, position, "harvest")
    return {"record": services.mask_record(result["record"], position), "merged": result["merged"]}


def analytics_unit(position: dict, unit: str | None) -> str:
    unit = unit or default_unit(position)
    if position["role"] in ("author", "supervisor"):
        raise HTTPException(403, "Аналитика кафедры доступна руководству и ответственному")
    check_unit(position, unit)
    return unit


@app.get("/api/analytics/overview")
def a_overview(unit: str | None = None, year: int = 2025, x_position: str | None = Header(None)):
    return analytics.overview(analytics_unit(position_of(x_position), unit), year)


@app.get("/api/analytics/teachers")
def a_teachers(unit: str | None = None, year: int = 2025, x_position: str | None = Header(None)):
    target = analytics_unit(position_of(x_position), unit)
    return {"items": analytics.teachers_table(target, year), "portal_total": analytics.portal_count(target)}


@app.get("/api/analytics/supervision")
def a_supervision(unit: str | None = None, year: int = 2025, x_position: str | None = Header(None)):
    position = position_of(x_position)
    if position["role"] == "supervisor":
        data = analytics.supervision_table(position["unit"], year, supervisor=position["person"])
        # Оқытушы тек өз шәкірттерін көреді, кафедра бойынша сан оған ашылмайды.
        data["linked"] = len({l["learner_id"] for g in data["groups"] for l in g["learners"]})
        data["missing"] = []
        return data
    return analytics.supervision_table(analytics_unit(position, unit), year)


@app.get("/api/analytics/compare")
def a_compare(parent: str | None = None, year: int = 2025, x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, "director", "science")
    parent = parent or position["unit"]
    check_unit(position, parent)
    data = analytics.compare(parent, year)
    data["facts"] = store.kv_get("school_facts") if parent == "vshet" else None
    return data


@app.get("/api/analytics/plan")
def a_plan(unit: str | None = None, year: int = 2025, x_position: str | None = Header(None)):
    return {"items": analytics.plan_fact(analytics_unit(position_of(x_position), unit), year)}


@app.put("/api/analytics/plan")
def a_plan_set(body: dict = Body(...), x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, "head", "director")
    current = store.kv_get("plan:mgmt:2025", {}) or {}
    for key, value in body.items():
        if key in current:
            current[key] = int(value)
    store.kv_set("plan:mgmt:2025", current)
    store.log(position, "План изменён", "mgmt/2025")
    return {"items": analytics.plan_fact("mgmt", 2025)}


@app.get("/api/analytics/risks")
def a_risks(x_position: str | None = Header(None)):
    position = position_of(x_position)
    data = analytics.risks("mgmt", 2025)
    if position["role"] == "author":
        data["doctoral"] = [d for d in data["doctoral"] if d["id"] == position["person"]]
    elif position["role"] == "supervisor":
        learners = {s["learner_id"] for s in store.supervisions() if s["supervisor_id"] == position["person"]}
        data["doctoral"] = [d for d in data["doctoral"] if d["id"] in learners]
    # Талап мәндері мысал және бір жылдық дерекке сүйенеді, сондықтан нақты адамның аты жасырылады.
    for i, d in enumerate(data["doctoral"], 1):
        if d["id"] != position["person"]:
            d["name"] = f"Докторант {i}"
            d["supervisors"] = []
            d["id"] = f"anon{i}"
    return data


@app.get("/api/journal/check")
def journal_check(issn: str = "", name: str = ""):
    watch = services.settings().get("journal_watchlist", [])
    tokens = set(validators.extract_issn(issn))
    hit = next((j for j in watch if j["issn"].replace("-", "") in tokens or (name and j["name"].lower() == name.lower())), None)
    valid = all(validators.issn_ok(t) for t in tokens) if tokens else None
    return {"risk": hit, "issn_valid": valid, "index": integrations.index_hint(issn, name)}


@app.get("/api/report/{unit}/{year}")
def report(unit: str, year: int, x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, *MANAGERS)
    check_unit(position, unit)
    rows = store.records(unit=unit, year=year, approved_only=True)
    persons = store.persons()
    schema = reporting.form_schema()
    outside = [services.item_view(r, position, persons) for r in store.records(unit=unit, year=year) if r.get("status") != store.APPROVED]
    sections = []
    for name in reporting.SHEET_NAMES:
        for item in schema["sheets"].get(name, {}).get("items", []):
            if item.get("header"):
                items = [card(r, position, persons) for r in rows if item["id"] in r.get("sections", [])]
                sections.append({"id": item["id"], "title": item["title"], "sheet": name, "count": len(items), "items": items[:50],
                                 "evidence": reporting.evidence_need(item["id"])})
    state = store.report_state(unit, year)
    versions = store.versions(unit, year)
    latest_diff = None
    if versions:
        snap = store.version_snapshot(unit, year, versions[0]["version"])
        latest_diff = services.diff_snapshots(snap, services.snapshot(unit, year))
    ind = analytics.indicators(unit, year)
    return {"unit": unit, "unit_name": store.units()[unit]["name"], "year": year, "sections": sections, "state": state,
            "actions": services.report_actions(unit, year, position), "versions": versions, "diff": latest_diff,
            "blocking": services.blocking_issues(unit, year), "indicators": ind, "manual": store.kv_get(f"manual:{unit}:{year}", {}),
            "evidence": reporting.evidence_summary(rows), "rows": len(rows), "can_edit_manual": position["role"] in ("responsible", "head"), "outside": outside,
            "auto_count": sum(1 for i in ind if i["source"] != "manual"), "manual_count": sum(1 for i in ind if i["source"] == "manual")}


@app.get("/api/report/{unit}/{year}/narrative")
def report_narrative(unit: str, year: int, x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, *MANAGERS)
    check_unit(position, unit)
    store.log(position, "Подготовлен черновик аналитической справки", f"{unit}/{year}")
    return agent.narrative(unit, year)


@app.put("/api/report/{unit}/{year}/manual")
def report_manual(unit: str, year: int, body: dict = Body(...), x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, "responsible", "head")
    check_unit(position, unit)
    guard_report_open(unit, year)
    current = store.kv_get(f"manual:{unit}:{year}", {}) or {}
    for key in ("degree_share", "foreign_scholar_share", "funding", "staff_count"):
        if key in body and body[key] not in ("", None):
            current[key] = float(body[key])
    store.kv_set(f"manual:{unit}:{year}", current)
    store.log(position, "Изменён показатель, вводимый вручную", f"{unit}/{year}", ", ".join(body.keys()))
    return {"manual": current}


@app.post("/api/report/{unit}/{year}/transition")
def report_transition(unit: str, year: int, body: dict = Body(...), x_position: str | None = Header(None)):
    position = position_of(x_position)
    check_unit(position, unit)
    result = services.transition(unit, year, body.get("action", ""), position, body.get("note", ""), body.get("protocol"), bool(body.get("force")))
    if result.get("blocked"):
        return JSONResponse(result, status_code=409)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


def _xlsx(data: bytes, filename: str) -> Response:
    from urllib.parse import quote

    return Response(content=data, media_type=XLSX, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


@app.get("/api/export/f605/{unit}/{year}")
def export_f605(unit: str, year: int, pos: str | None = Query(None), version: int | None = None):
    position = position_of(pos)
    require(position, *MANAGERS)
    check_unit(position, unit)
    # Утверждённый отчёт выгружается в подписанной версии, а не из текущих данных.
    versions = store.versions(unit, year)
    if not version and versions and store.report_state(unit, year)["status"] in ("согласовано", "принято"):
        version = versions[0]["version"]
    snap = store.version_snapshot(unit, year, version) if version else services.snapshot(unit, year)
    if not snap:
        raise HTTPException(404, "Версия не найдена")
    pii = services.pii_allowed(position)
    store.log(position, "Выгружен отчёт Excel", f"{unit}/{year}", f"версия={version or 'текущая'}, контакты={'открыты' if pii else 'скрыты'}")
    return _xlsx(reporting.f605_bytes(snap, pii=pii), f"ОТЧЕТ_НИР_{store.units()[unit]['name']}_{year}.xlsx")


@app.get("/api/export/person/{person_id}")
def export_person(person_id: str, pos: str | None = Query(None)):
    position = position_of(pos)
    if person_id != position["person"] and position["role"] not in MANAGERS:
        raise HTTPException(403, "Можно выгрузить только свой список")
    if person_id not in store.persons():
        raise HTTPException(404, "Не найдено")
    store.log(position, "Выгружен список научных работ", person_id)
    return _xlsx(reporting.person_list_bytes(person_id), "Список_научных_работ.xlsx")


@app.get("/api/export/department/{unit}/{year}")
def export_department(unit: str, year: int, pos: str | None = Query(None)):
    position = position_of(pos)
    require(position, *MANAGERS)
    check_unit(position, unit)
    store.log(position, "Выгружен научный раздел отчёта кафедры", f"{unit}/{year}")
    return _xlsx(reporting.department_section_bytes(unit, year), f"Научный_раздел_кафедры_{year}.xlsx")


@app.get("/api/export/summary/{parent}/{year}")
def export_summary(parent: str, year: int, pos: str | None = Query(None)):
    position = position_of(pos)
    require(position, "director", "science")
    check_unit(position, parent)
    store.log(position, "Выгружена сводная таблица", f"{parent}/{year}")
    return _xlsx(reporting.summary_bytes(parent, year), f"Сводная_{parent}_{year}.xlsx")


@app.get("/api/export/evidence/{unit}/{year}")
def export_evidence(unit: str, year: int, pos: str | None = Query(None)):
    position = position_of(pos)
    require(position, *MANAGERS)
    check_unit(position, unit)
    store.log(position, "Выгружен пакет подтверждающих документов", f"{unit}/{year}")
    return Response(content=reporting.evidence_zip_bytes(unit, year), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename=evidence_{unit}_{year}.zip"})


@app.get("/api/campaign")
def get_campaign(year: int = 2025, x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, *MANAGERS)
    return services.campaign_status(year)


@app.put("/api/campaign")
def put_campaign(body: dict = Body(...), x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, "science")
    store.set_campaign(int(body.get("year", 2025)), body["deadline"], body.get("title", "Отчёт НИР"), position["label"])
    store.log(position, "Изменён срок кампании отчётности", "", body["deadline"])
    return services.campaign_status(int(body.get("year", 2025)))


@app.post("/api/campaign/remind")
def campaign_remind(body: dict = Body(default={}), x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, *MANAGERS)
    return {"sent": services.remind(position, body.get("unit"), body.get("person"))}


@app.post("/api/campaign/remind-all")
def campaign_remind_all(x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, *MANAGERS)
    return services.remind_all(position)


@app.get("/api/notifications")
def notifications(x_position: str | None = Header(None)):
    return {"items": store.notifications(position_of(x_position))}


@app.post("/api/notifications/read")
def notifications_read(x_position: str | None = Header(None)):
    store.mark_notifications_read(position_of(x_position))
    return {"ok": True}


@app.get("/api/inpress")
def in_press(x_position: str | None = Header(None)):
    position = position_of(x_position)
    persons = store.persons()
    rows = [r for r in services.visible_records(position) if r.get("in_press")]
    return {"items": [card(r, position, persons) for r in rows]}


@app.post("/api/records/{rid}/check-published")
def check_published(rid: str, x_position: str | None = Header(None)):
    """Crossref-тен шыққанын тексереді. Табылса, бет нөмірін автор растап жаңартады."""
    position = position_of(x_position)
    rec = store.record(rid)
    if not rec or not services.can_see(position, rec):
        raise HTTPException(404, "Запись не найдена")
    hit = integrations.crossref_by_doi(rec["fields"]["doi"]) if rec["fields"].get("doi") else integrations.crossref_by_title(rec["fields"].get("title", ""))
    store.log(position, "Проверен выход публикации", rid, "найдено" if hit else "не найдено")
    if not hit:
        return {"found": False, "text": "В Crossref пока не найдено. Отечественные журналы могут там не регистрироваться."}
    if rec.get("status") == store.APPROVED and services.is_author(position, rec) and not services.report_locked(rec["unit"], rec["year"]):
        services.apply_published(rid, hit["fields"], position)
        return {"found": True, "applied": True, "fields": hit["fields"], "text": "Статья вышла: страницы и номер обновлены из Crossref."}
    return {"found": True, "fields": hit["fields"], "text": "Найдено в Crossref. Проверьте данные и сохраните."}


@app.post("/api/audit/upload")
async def audit_upload(file: UploadFile = File(...), x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, *MANAGERS)
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(415, "Загрузите файл XLSX")
    data = await file.read()
    if len(data) > agent.MAX_FILE_BYTES:
        raise HTTPException(413, "Файл слишком большой")
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        result = audit.run_audit(path)
    except Exception as exc:  # бұзылған немесе басқа пішімдегі Excel кез келген қате тастауы мүмкін
        raise HTTPException(400, f"Не удалось прочитать файл: {exc.__class__.__name__}") from exc
    finally:
        pass
    if result.get("error"):
        os.unlink(path)
        raise HTTPException(400, result["error"])
    result["audit_id"] = store.save_audit({"path": path, "filename": file.filename})
    store.log(position, "Отчёт проверен", file.filename or "", f"ошибок {result['errors']}, предупреждений {result['warnings']}")
    return result


@app.post("/api/audit/{aid}/import")
def audit_import(aid: str, x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, "responsible", "head")
    guard_report_open("mgmt", 2025)
    doc = store.get_audit(aid)
    if not doc or not Path(doc["path"]).exists():
        raise HTTPException(404, "Аудит не найден")
    result = audit.import_rows(doc["path"], position)
    os.unlink(doc["path"])
    return result


@app.get("/api/integrations")
def integrations_status(x_position: str | None = Header(None)):
    position_of(x_position)
    return {"items": [
        {"id": "crossref", "name": "Crossref", "status": "live", "text": "Отправляет реальные запросы по DOI и ORCID"},
        {"id": "openalex", "name": "OpenAlex", "status": "live" if os.environ.get("OPENALEX_API_KEY") else "needs_key", "text": "Ищет по ORCID, нужен бесплатный API-ключ"},
        {"id": "smartenu", "name": "Smart.ENU «Научные работы»", "status": "mock", "text": "Главный источник публикаций: модуль берёт статьи, конференции и монографии отсюда. Тестовый адаптер: в демо страница и модуль работают с одной базой. Для реального подключения нужен API Департамента цифрового развития."},
        {"id": "platonus", "name": "Импорт из Platonus", "status": "mock", "text": "Тестовый адаптер: воспроизводит результат импорта Platonus в Smart.ENU."},
        {"id": "scopus", "name": "Импорт из Scopus", "status": "mock", "text": "Тестовый адаптер: воспроизводит результат импорта Scopus в Smart.ENU."},
        {"id": "bilge", "name": "Специалист Bilge", "status": "mock", "text": "Агент вызывается через отдельный API. Для подключения к Bilge нужно согласование с её разработчиками."},
        {"id": "sso", "name": "Должность в Smart.ENU", "status": "mock", "text": "В демо должность меняется вручную. В работе должность приходит из Smart.ENU."},
    ]}


@app.post("/api/integrations/{name}/import")
def integration_import(name: str, x_position: str | None = Header(None)):
    position = position_of(x_position)
    mock = store.kv_get("mock_import", {}) or {}
    items = mock.get(name)
    if items is None:
        raise HTTPException(404, "Такого адаптера нет")
    # Әркім өз деректерін ғана импорттайды.
    items = [i for i in items if i["person"] == position["person"]]
    imported = store.kv_get("imported", {}) or {}
    if imported.get(name) or not items:
        return {"added": 0, "merged": 0, "text": "Новых записей из этого источника нет"}
    added, merged = 0, 0
    for item in items:
        pos = {**position, "role": "author", "unit": "mgmt"}
        payload = {"type": item["type"], "fields": item["fields"], "attrs": item["attrs"], "ai": {"mode": "import", "verified_by": name}}
        result = services.create_record(payload, pos, name)
        if not result["merged"]:
            result["record"]["confirmed"] = False
            result["record"]["pending_for"] = [item["person"]]
            store.save_record(result["record"])
        merged += bool(result["merged"])
        added += not result["merged"]
    imported[name] = True
    store.kv_set("imported", imported)
    store.log(position, f"{name}: тестовый импорт", "", f"добавлено {added}, объединено {merged}")
    return {"added": added, "merged": merged, "text": f"Добавлено записей: {added}, ожидают подтверждения автора"}


@app.post("/api/bilge/specialist")
async def bilge_specialist(session: str = Form("bilge"), text: str = Form(""), file: UploadFile | None = File(None), x_position: str | None = Header(None)):
    """Bilge шақыратын маман келісімі: мәтін не файл қабылдап, жауап пен карточка қайтарады."""
    return await _agent_call(session, text, file, x_position)


async def _agent_call(session: str, text: str, file: UploadFile | None, x_position: str | None) -> dict:
    position = position_of(x_position)
    upload = None
    if file is not None:
        upload = {"name": file.filename or "file", "data": await file.read(), "mime": file.content_type or ""}
    return agent.message(f"{x_position}:{session}", text, upload, position)


@app.post("/api/agent/message")
async def agent_message(session: str = Form("default"), text: str = Form(""), file: UploadFile | None = File(None), x_position: str | None = Header(None)):
    return await _agent_call(session, text, file, x_position)


@app.post("/api/agent/stream")
async def agent_stream(session: str = Form("default"), text: str = Form(""), file: UploadFile | None = File(None), x_position: str | None = Header(None)):
    """Агент қадамдарын, мәтінді, карточка мен диаграмманы дайын болған сайын жібереді."""
    position = position_of(x_position)
    upload = None
    if file is not None:
        upload = {"name": file.filename or "file", "data": await file.read(), "mime": file.content_type or ""}
    events: queue.Queue = queue.Queue()

    def work() -> None:
        try:
            result = agent.message(f"{x_position}:{session}", text, upload, position, emit=events.put)
            events.put({"type": "done", "reply": result["reply"], "mode": result["mode"]})
        except Exception as exc:  # ағын үзілмей, пайдаланушы түсінікті жауап алуы керек
            store.log(position, "Ошибка агента", session[:8], exc.__class__.__name__)
            events.put({"type": "error", "text": "Запрос не выполнен. Попробуйте ещё раз."})
        events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        while (item := events.get()) is not None:
            yield "data: " + json.dumps(item, ensure_ascii=False, default=str) + "\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/scientists")
def scientists(x_position: str | None = Header(None)):
    position_of(x_position)
    rows = [p for p in store.persons().values() if p.get("on_portal") and p["role"] == "teacher"]
    rows.sort(key=lambda p: p.get("full_name") or p["display_name"])
    return {"items": [{"id": p["id"], "name": p.get("full_name") or p["display_name"], "degree": p.get("degree", "")} for p in rows]}


@app.post("/api/agent/reset")
def agent_reset(session: str = Body("default", embed=True), x_position: str | None = Header(None)):
    agent.reset(f"{x_position}:{session}")
    return {"ok": True}


@app.get("/api/settings")
def get_settings(x_position: str | None = Header(None)):
    position_of(x_position)
    return services.settings()


@app.put("/api/settings")
def put_settings(body: dict = Body(...), x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, "science")
    current = services.settings()
    for key in ("journal_watchlist", "doctoral_requirements"):
        if key in body:
            current[key] = body[key]
    store.kv_set("settings", current)
    store.log(position, "Настройки изменены")
    return current


@app.get("/api/log")
def get_log(x_position: str | None = Header(None)):
    position = position_of(x_position)
    require(position, *MANAGERS)
    return {"items": store.logs()}


@app.post("/api/demo/reset")
def demo_reset(x_position: str | None = Header(None)):
    require(position_of(x_position), *MANAGERS)
    store.seed_if_empty(force=True)
    return {"ok": True}


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")

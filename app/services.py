"""Жазба құру, тексеру, біріктіру және есеп процесі. Форма да, чат-агент та осы қабатты қолданады."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from . import integrations, store, validators
from .catalog import TYPES, display_title
from .names import match_person, norm_title

LEARNERS = ("student", "master", "doctoral")
AUTHOR_ROLES = ("teacher",) + LEARNERS
EDITABLE_STATUSES = ("создано", "на доработке")
LOCKED_REPORT_STATUSES = ("на подписании", "согласовано", "принято")
NO_SECTION_TEXT = "Раздел отчёта не определён: в форме нет такого списка для этого вида и автора. Проверьте вид записи, индекс, место и язык."


def settings() -> dict:
    return store.kv_get("settings", {}) or {}


def awaiting_confirmation(rec: dict) -> list[str]:
    """Жазбаны кім растауы керек. Белгіленбесе, барлық автор."""
    if rec.get("confirmed"):
        return []
    return rec.get("pending_for") or rec.get("author_ids", [])


def missing_required(rec_type: str, fields: dict, attrs: dict) -> list[dict]:
    spec = TYPES.get(rec_type)
    if not spec:
        return []
    out = []
    for f in spec["fields"]:
        if f.get("required") and not str(fields.get(f["key"], "") or "").strip():
            out.append({"key": f["key"], "label": f["label"]})
    for a in spec.get("attrs", []):
        if a.get("required") and not attrs.get(a["key"]):
            out.append({"key": a["key"], "label": a["label"], "attr": True})
    return out


def resolve_authors(raw_authors: list[str]) -> dict:
    """Авторларды анықтамалықпен серверде салыстырады. Модельге тек нәтиже мәртебесі қайтады."""
    persons = [p for p in store.persons().values() if p["role"] != "manager"]
    matched, external = [], []
    for raw in raw_authors or []:
        hit = match_person(raw, persons)
        if hit["person_id"] and hit["score"] >= 0.75:
            p = next(x for x in persons if x["id"] == hit["person_id"])
            matched.append({"raw": raw, "person_id": p["id"], "display": p["display_name"], "role": p["role"], "score": hit["score"]})
        else:
            external.append(raw)
    return {"matched": matched, "external": external}


def find_existing(fields: dict, exclude: str | None = None) -> dict | None:
    title = norm_title(fields.get("title", ""))
    doi = (fields.get("doi") or "").lower()
    for r in store.records():
        if r["id"] == exclude:
            continue
        if doi and (r["fields"].get("doi") or "").lower() == doi:
            return r
        if title and len(title) > 15 and norm_title(r["fields"].get("title", "")) == title:
            return r
    return None


def preview(payload: dict, position: dict) -> dict:
    """Сақтамай тұрып бөлімді, қатені, қайталануды көрсетеді."""
    rec_type = payload.get("type") or "article"
    fields = {k: v for k, v in (payload.get("fields") or {}).items() if v not in (None, "")}
    attrs = dict(payload.get("attrs") or {})
    raw_authors = payload.get("authors") or []
    author_ids = list(payload.get("author_ids") or [])
    resolved = resolve_authors(raw_authors)
    ids = author_ids + [m["person_id"] for m in resolved["matched"] if m["person_id"] not in author_ids]
    persons = store.persons()
    me = position.get("person")
    if (position.get("role") in ("author", "supervisor") or payload.get("as_author")) and me and me not in ids:
        ids.insert(0, me)
    roles = []
    for pid in ids:
        role = persons.get(pid, {}).get("role")
        if role in AUTHOR_ROLES and role not in roles:
            roles.append(role)
    if rec_type in ("prize", "project"):
        roles = [r for r in roles if r in LEARNERS] or [persons.get(me, {}).get("role", "student")]
    if rec_type in ("award", "scholarship", "editorial", "monograph"):
        roles = ["teacher"]
    if not roles:
        roles = ["teacher"]
    if rec_type == "article" and not attrs.get("index"):
        hint = integrations.index_hint(fields.get("issn", ""), fields.get("source", ""))
        if hint:
            attrs["index"] = hint["index"]
            attrs["index_basis"] = hint["basis"]
    draft = {"id": payload.get("id") or "draft", "type": rec_type, "roles": roles, "attrs": attrs, "fields": fields, "matrix": payload.get("matrix") or {},
             "author_ids": ids, "external_authors": resolved["external"] + list(payload.get("external_authors") or []),
             "in_press": bool(payload.get("in_press")), "year": _year(fields, payload.get("year")), "unit": position.get("unit") if position.get("unit") not in ("uni", "vshet") else "mgmt"}
    existing = find_existing(fields, exclude=payload.get("id"))
    if existing:
        # Базадағы жазбаның түрі, белгілері мен бөлімдері сақталады. Жаңа бөлім тек жаңа автор қосылса пайда болады:
        # автордың бүгінгі мәртебесі бұрынғы жылдың жазбасын басқа бөлімге көшірмейді.
        draft["type"] = rec_type = existing["type"]
        for key, value in existing.get("attrs", {}).items():
            attrs.setdefault(key, value)
        added_roles = [persons.get(pid, {}).get("role") for pid in ids if pid not in existing.get("author_ids", [])]
        draft["roles"] = list(existing.get("roles", [])) + [r for r in added_roles if r in AUTHOR_ROLES and r not in existing.get("roles", [])]
    draft["sections"] = store.compute_sections(draft)
    if existing:
        draft["sections"] = list(dict.fromkeys(existing.get("sections", []) + draft["sections"]))
    draft["section"] = draft["sections"][0] if draft["sections"] else None
    issues = validators.check_record(draft, settings().get("journal_watchlist"))
    return {"record": draft, "issues": issues, "missing": missing_required(rec_type, fields, attrs) if not existing else [],
            "authors": resolved["matched"], "external": draft["external_authors"],
            "duplicate": {"id": existing["id"], "title": display_title(existing), "sections": existing.get("sections", [])} if existing else None,
            "ai": payload.get("ai")}


def _year(fields: dict, fallback) -> int:
    m = re.search(r"(20\d{2})", str(fields.get("year") or ""))
    if m:
        return int(m.group(1))
    return int(fallback or 2025)


def clean_evidence(items: list | None) -> list[dict]:
    """Клиент жіберген файл сілтемесіне сенбейміз: тек сервер сақтаған файл атауы қабылданады."""
    out = []
    for item in items or []:
        stored = str((item or {}).get("stored", ""))
        if store.upload_path(stored):
            out.append({"filename": Path(str(item.get("filename") or stored)).name, "stored": stored, "size": item.get("size"), "at": item.get("at")})
    return out


def create_record(payload: dict, position: dict, source: str = "form") -> dict:
    view = preview(payload, position)
    if view["duplicate"] and not payload.get("force_new"):
        return merge_into(view["duplicate"]["id"], view["record"], position, source)
    rec = view["record"]
    rec["id"] = store.new_record_id()
    persons = store.persons()
    supervisors = []
    for s in store.supervisions():
        if s["learner_id"] in rec["author_ids"] and s["kind"] == "main" and s["supervisor_id"] not in supervisors:
            supervisors.append(s["supervisor_id"])
    rec.update({"supervisor_ids": supervisors, "source": source, "status": "создано", "confirmed": True,
                "confirmed_by": [position.get("person")], "created_by": position.get("person"),
                "created_at": store.now(), "evidence": clean_evidence(payload.get("evidence")),
                "ai": payload.get("ai"), "reported_section": rec["sections"][0] if rec["sections"] else None,
                "route": [], "stage_since": store.now(),
                "history": [{"at": store.now(), "by": position.get("label"), "action": "Запись создана", "note": ""}]})
    rec = store.save_record(rec)
    store.log(position, "Запись добавлена", rec["id"], f"{source}: {display_title(rec)[:80]}")
    for pid in rec["author_ids"]:
        if pid != position.get("person") and persons.get(pid, {}).get("role") != "external":
            store.notify(f"Вас отметили соавтором: {display_title(rec)[:70]}. Вводить повторно не нужно.",
                         person=pid, link=f"records/{rec['id']}")
    return {"record": rec, "merged": False}


def merge_into(target_id: str, incoming: dict, position: dict, source: str) -> dict:
    """Жаңа дерек бар жазбаға қосылады, сондықтан адам екінші рет енгізбейді.

    Өзгерту құқығы жоқ адам жазбаны өзгертпейді және оны ашып көрмейді: соавтор екенін ғана мәлімдейді, шешімді жауапты қабылдайды.
    """
    target = store.record(target_id)
    if not can_edit(position, target):
        me = position.get("person")
        claimed = bool(me) and me not in target.get("author_ids", [])
        if claimed and me not in target.setdefault("claims", []):
            target["claims"].append(me)
            store.save_record(target)
            name = store.persons().get(me, {}).get("display_name", "")
            store.notify(f"{name} указывает себя соавтором записи: {display_title(target)[:70]}. Проверьте и примите решение.",
                         role="responsible", unit=target.get("unit"), link=f"record/{target_id}")
        store.log(position, "Повтор предотвращён", target_id, f"{source}: запись не изменена")
        return {"record": {"id": target["id"], "title": display_title(target), "sections": target.get("sections", [])}, "merged": True, "filled": [], "claimed": claimed}
    changed = []
    for key, value in (incoming.get("fields") or {}).items():
        if value and not target["fields"].get(key):
            target["fields"][key] = value
            changed.append(key)
    for pid in incoming.get("author_ids", []):
        if pid not in target["author_ids"]:
            target["author_ids"].append(pid)
    for role in incoming.get("roles", []):
        if role not in target.get("roles", []):
            target["roles"].append(role)
    target["sections"] = store.compute_sections(target) or target.get("sections", [])
    target["confirmed"] = True
    target = store.save_record(target)
    store.log(position, "Повтор предотвращён", target_id, f"{source}: заполнено полей: {len(changed)}")
    return {"record": target, "merged": True, "filled": changed}


def scope_units(position: dict) -> list[str] | None:
    role = position.get("role")
    if role == "science":
        return None
    if role == "director":
        from .analytics import descendants
        return descendants(position.get("unit"))
    return [position.get("unit")]


def visible_records(position: dict, year: int | None = None, mine_only: bool = False) -> list[dict]:
    rows = store.records(year=year)
    role = position.get("role")
    me = position.get("person")
    if role in ("author",) or mine_only:
        return [r for r in rows if me in r.get("author_ids", [])]
    if role == "supervisor":
        learners = {s["learner_id"] for s in store.supervisions() if s["supervisor_id"] == me}
        return [r for r in rows if me in r.get("author_ids", []) or (set(r.get("author_ids", [])) & learners)
                or any(s.get("person") == me for s in r.get("route", []))]
    units = scope_units(position)
    if units is None:
        return rows
    return [r for r in rows if r["unit"] in units]


def can_see(position: dict, rec: dict) -> bool:
    return any(r["id"] == rec["id"] for r in visible_records(position))


def can_edit(position: dict, rec: dict) -> bool:
    # Автор жазбаны тек жіберілгенге дейін не қайтарылғанда өзгертеді, келісілген дерек өздігінен өзгермейді.
    # Басшы болса да өз жазбасына осы ереже қолданылады.
    own = position.get("person") in rec.get("author_ids", [])
    if own and rec.get("status") not in EDITABLE_STATUSES:
        return False
    if position.get("role") in ("responsible", "head"):
        return rec["unit"] == position.get("unit")
    return own and rec.get("status") in EDITABLE_STATUSES


def report_locked(unit: str, year: int) -> bool:
    """Есеп қол қоюға кеткен соң оның сандары өзгермеуі керек."""
    return store.report_state(unit, year)["status"] in LOCKED_REPORT_STATUSES


def pii_allowed(position: dict) -> bool:
    return position.get("role") == "responsible"


def mask_record(rec: dict, position: dict) -> dict:
    """Телефон мен email тек есеп дайындайтын жауаптыға және жазба иесіне ашылады."""
    out = dict(rec)
    fields = dict(rec.get("fields", {}))
    allowed = pii_allowed(position) or position.get("person") in rec.get("author_ids", [])
    for key in ("phone", "email"):
        if key in fields and not allowed:
            fields[key] = "•••"
    fields.pop("_reported_department", None)
    out["fields"] = fields
    return out


def record_issues(rows: list[dict] | None = None) -> dict[str, list[dict]]:
    rows = rows if rows is not None else store.records()
    watch = settings().get("journal_watchlist")
    coll = validators.check_collection(rows)
    out = {}
    for r in rows:
        out[r["id"]] = validators.check_record(r, watch) + coll.get(r["id"], [])
    return out


def duplicates(rows: list[dict] | None = None) -> list[dict]:
    rows = rows if rows is not None else store.records()
    return validators.find_duplicates(rows)


def review_queue(unit: str = "mgmt", year: int = 2025) -> dict:
    rows = store.records(unit=unit, year=year, approved_only=True)
    issues = record_issues(rows)
    dups = duplicates(rows)
    dup_ids = {i for d in dups if d["kind"] != "similar" for i in d["record_ids"]}
    items = []
    auto_ok = 0
    for r in rows:
        own = [i for i in issues.get(r["id"], []) if i["level"] in ("error", "warn") and i["code"] not in r.get("dismissed", [])]
        low = [k for k, v in ((r.get("ai") or {}).get("confidence") or {}).items() if isinstance(v, (int, float)) and v < 0.7]
        if not own and not low and r["id"] not in dup_ids:
            auto_ok += 1
            continue
        if not own and not low:
            continue
        items.append({"id": r["id"], "title": display_title(r), "type": r["type"], "sections": r.get("sections", []),
                      "issues": own, "low_confidence": low, "level": "error" if any(i["level"] == "error" for i in own) else "warn",
                      "source": r.get("source")})
    items.sort(key=lambda x: (x["level"] != "error", x["id"]))
    counts = {}
    for r in rows:
        for i in issues.get(r["id"], []):
            if i["code"] not in r.get("dismissed", []):
                counts[i["code"]] = counts.get(i["code"], 0) + 1
    enriched = []
    by_id = {r["id"]: r for r in rows}
    for d in dups:
        enriched.append({**d, "records": [{"id": i, "title": display_title(by_id[i]), "sections": by_id[i].get("sections", []),
                                            "pages": by_id[i]["fields"].get("pages", ""), "source": by_id[i]["fields"].get("source", "")[:70],
                                            "ref": by_id[i].get("source_ref")} for i in d["record_ids"]]})
    return {"total": len(rows), "auto_ok": auto_ok, "items": items, "duplicates": enriched, "counts": counts,
            "need_review": len(items) + sum(1 for d in dups if d["kind"] != "similar" and not any(i["id"] in d["record_ids"] for i in items))}


def merge_duplicates(record_ids: list[str], primary: str | None, position: dict) -> dict:
    rows = [store.record(i) for i in record_ids]
    rows = [r for r in rows if r]
    if len(rows) < 2:
        return {"error": "Для объединения нужно минимум две записи"}
    order = {"wos": 0, "scopus": 1, "koksnvo": 2}
    if primary:
        main = next(r for r in rows if r["id"] == primary)
    else:
        main = sorted(rows, key=lambda r: (order.get(r["attrs"].get("index"), 5), r["id"]))[0]
    for r in rows:
        if r["id"] == main["id"]:
            continue
        for key, value in r["fields"].items():
            if value and not main["fields"].get(key):
                main["fields"][key] = value
        for pid in r.get("author_ids", []):
            if pid not in main["author_ids"]:
                main["author_ids"].append(pid)
        for pid in r.get("supervisor_ids", []):
            if pid not in main.setdefault("supervisor_ids", []):
                main["supervisor_ids"].append(pid)
        same_prefix = {s[0] for s in r.get("sections", [])} & {s[0] for s in main.get("sections", [])}
        for role in r.get("roles", []):
            if role not in main["roles"]:
                main["roles"].append(role)
        if not same_prefix:
            for s in r.get("sections", []):
                if s not in main["sections"]:
                    main["sections"].append(s)
        r["merged_into"] = main["id"]
        store.save_record(r)
    computed = store.compute_sections(main)
    main["sections"] = computed or main["sections"]
    main.setdefault("merged_from", []).extend([r["id"] for r in rows if r["id"] != main["id"]])
    store.save_record(main)
    store.log(position, "Повторяющиеся записи объединены", main["id"], ", ".join(record_ids))
    return {"record": store.record(main["id"]), "merged": len(rows) - 1}


FIXES = {
    "PLACE_MISMATCH": "Исправить раздел",
    "JOURNAL_IN_CONFERENCE": "Перенести в журнальные статьи",
    "ISSN_IN_ISBN": "Перенести в журнальные статьи",
}


def fix_issue(rid: str, code: str, position: dict) -> dict | None:
    rec = store.record(rid)
    if not rec:
        return None
    if code == "PLACE_MISMATCH":
        if rec["type"] == "scholarship":
            rec["attrs"]["place"] = "kz"
        else:
            rec["attrs"]["place"] = "abroad"
    elif code in ("JOURNAL_IN_CONFERENCE", "ISSN_IN_ISBN"):
        rec["type"] = "article"
        rec["attrs"] = {"index": "foreign_other" if re.search(r"рф|москв|российск|international|молодой|вестник науки", rec["fields"].get("source", ""), re.I) else "other",
                        **{k: v for k, v in rec["attrs"].items() if k.startswith("coauthor")}}
        value = rec["fields"].pop("isbn", "")
        if value:
            rec["fields"]["issn"] = value
    else:
        return rec
    rec["sections"] = store.compute_sections(rec) or rec["sections"]
    rec["reviewed_fix"] = code
    store.save_record(rec)
    store.log(position, "Раздел исправлен", rid, f"{code}: {rec['sections']}")
    return store.record(rid)


def dismiss_issue(rid: str, code: str, position: dict) -> dict | None:
    rec = store.record(rid)
    if not rec:
        return None
    if code not in rec.setdefault("dismissed", []):
        rec["dismissed"].append(code)
    store.save_record(rec)
    store.log(position, "Предупреждение принято", rid, code)
    return store.record(rid)


def dismiss_code(code: str, unit: str, year: int, position: dict) -> int:
    """Бір түрдегі ескертуді бірден қабылдайды: жауапты жолдарды бір-бірлеп баспайды."""
    rows = store.records(unit=unit, year=year, approved_only=True)
    issues = record_issues(rows)
    count = 0
    for r in rows:
        if any(i["code"] == code for i in issues[r["id"]]) and code not in r.get("dismissed", []):
            r.setdefault("dismissed", []).append(code)
            store.save_record(r)
            count += 1
    store.log(position, "Тип предупреждения принят группой", code, f"записей: {count}")
    return count


def update_record(rid: str, patch: dict, position: dict) -> dict | None:
    rec = store.record(rid)
    if not rec:
        return None
    changed = []
    for key, value in (patch.get("fields") or {}).items():
        # Жасырылған байланыс мәні кері келсе, нақты мәнді сақтап қаламыз.
        if key in ("phone", "email") and value == "•••":
            continue
        if rec["fields"].get(key) != value and not (value in ("", None) and key not in rec["fields"]):
            changed.append(key)
        if value in ("", None):
            rec["fields"].pop(key, None)
        else:
            rec["fields"][key] = value
    if "year" in changed:
        rec["year"] = _year(rec["fields"], rec.get("year"))
    if patch.get("attrs"):
        rec["attrs"].update(patch["attrs"])
    if changed and rec.get("status") == store.APPROVED:
        _history(rec, position, "Данные согласованной записи изменены", ", ".join(changed))
    if "in_press" in patch:
        rec["in_press"] = bool(patch["in_press"])
    elif rec.get("in_press") and re.fullmatch(r"\s*\d+\s*[-–—]\s*\d+\s*", rec["fields"].get("pages", "")):
        rec["in_press"] = False
    rec["sections"] = store.compute_sections(rec) or rec["sections"]
    store.save_record(rec)
    store.log(position, "Запись изменена", rid, ", ".join((patch.get("fields") or {}).keys()))
    return store.record(rid)


# Есеп процесі: создано → на согласовании → на подписании → согласовано → принято; кез келген кезеңнен на доработке.
TRANSITIONS = {
    "submit": {"from": ("создано", "на доработке"), "to": "на согласовании", "roles": ("responsible",), "label": "Отправить на согласование"},
    "approve": {"from": ("на согласовании",), "to": "на подписании", "roles": ("head",), "label": "Согласовать и отправить на подпись"},
    "sign": {"from": ("на подписании",), "to": "согласовано", "roles": ("director",), "label": "Подписать и утвердить"},
    "accept": {"from": ("согласовано",), "to": "принято", "roles": ("science",), "label": "Принять отчёт"},
    "return": {"from": ("на согласовании", "на подписании", "согласовано"), "to": "на доработке", "roles": ("head", "director", "science"), "label": "Вернуть на доработку"},
}
# Әр рөл есепті тек өз кезеңінде қайтара алады.
RETURN_FROM = {"head": ("на согласовании",), "director": ("на подписании", "согласовано"), "science": ("согласовано",)}


def _action_allowed(key: str, status: str, role: str | None) -> bool:
    t = TRANSITIONS[key]
    if status not in t["from"] or role not in t["roles"]:
        return False
    return key != "return" or status in RETURN_FROM.get(role, ())


def report_actions(unit: str, year: int, position: dict) -> list[dict]:
    status = store.report_state(unit, year)["status"]
    return [{"action": key, "label": t["label"]} for key, t in TRANSITIONS.items() if _action_allowed(key, status, position.get("role"))]


def blocking_issues(unit: str, year: int) -> int:
    rows = store.records(unit=unit, year=year, approved_only=True)
    issues = record_issues(rows)
    return sum(1 for r in rows for i in issues[r["id"]] if i["level"] == "error" and i["code"] not in r.get("dismissed", []))


def snapshot(unit: str, year: int) -> dict:
    from .analytics import indicators
    persons = store.persons()
    rows = store.records(unit=unit, year=year, approved_only=True)
    ids = {a for r in rows for a in r.get("author_ids", []) + r.get("supervisor_ids", [])}
    return {"unit": unit, "year": year, "records": rows, "indicators": indicators(unit, year),
            "persons": {i: {k: persons[i].get(k, "") for k in ("display_name", "display_latin", "role", "group", "degree", "position", "phone", "email")}
                        for i in ids if i in persons},
            "state": {k: v for k, v in store.report_state(unit, year).items() if k in ("protocol",)}}


def diff_snapshots(old: dict, new: dict) -> dict:
    a = {r["id"]: r for r in old["records"]}
    b = {r["id"]: r for r in new["records"]}
    changed = [i for i in a.keys() & b.keys() if a[i]["fields"] != b[i]["fields"] or a[i].get("sections") != b[i].get("sections")]
    ind_old = {x["row"]: x["value"] for x in old["indicators"]}
    ind = [{"row": x["row"], "label": x["label"], "old": ind_old.get(x["row"]), "new": x["value"]}
           for x in new["indicators"] if ind_old.get(x["row"]) != x["value"]]
    return {"added": [display_title(b[i]) for i in b.keys() - a.keys()],
            "removed": [display_title(a[i]) for i in a.keys() - b.keys()],
            "changed": [display_title(b[i]) for i in changed], "indicators": ind}


def transition(unit: str, year: int, action: str, position: dict, note: str = "", protocol: dict | None = None, force: bool = False) -> dict:
    t = TRANSITIONS.get(action)
    state = store.report_state(unit, year)
    if not t or state["status"] not in t["from"]:
        return {"error": "На этом этапе такое действие недоступно"}
    if not _action_allowed(action, state["status"], position.get("role")):
        return {"error": "У вас нет прав на это действие"}
    if action == "submit" and not force:
        blocking = blocking_issues(unit, year)
        if blocking:
            return {"blocked": blocking, "error": f"В отчёте ошибок: {blocking}. Сначала исправьте их или отправьте всё равно."}
    if protocol:
        state["protocol"] = protocol
    state.setdefault("history", []).append({"at": store.now(), "by": position.get("label"), "action": t["label"], "note": note, "to": t["to"]})
    version = None
    if action == "sign":
        version = store.add_version(unit, year, position.get("label", ""), snapshot(unit, year))
    store.set_report_state(unit, year, t["to"], state)
    store.log(position, f"Отчёт: {t['label']}", f"{unit}/{year}", note)
    role_next = {"на согласовании": "head", "на подписании": "director", "на доработке": "responsible", "согласовано": "science", "принято": "responsible"}.get(t["to"])
    if role_next:
        target_unit = {"director": "vshet", "science": "uni"}.get(role_next, unit)
        store.notify(f"Отчёт за {year} год перешёл на этап «{t['to']}».", role=role_next, unit=target_unit, link="report")
    return {"status": t["to"], "version": version}


def campaign_status(year: int = 2025) -> dict:
    from .analytics import unit_tree
    tree = unit_tree()
    camp = store.campaign(year)
    rows = []
    for uid in tree["children"].get("vshet", []):
        u = tree["units"][uid]
        state = store.report_state(uid, year)
        if uid == "mgmt":
            recs = store.records(unit="mgmt", year=year)
            total = len(recs)
            done = sum(1 for r in recs if r.get("status") == store.APPROVED)
        else:
            seed = sum(ord(c) for c in uid)
            total = 90 + seed % 80
            done = int(total * (0.45 + (seed % 50) / 100))
        rows.append({"id": uid, "name": u["name"], "status": state["status"], "total": total, "done": min(done, total),
                     "percent": round(min(done, total) * 100 / total) if total else 0, "synthetic": bool(u.get("synthetic"))})
    pending = []
    persons = store.persons()
    todo: dict[str, set] = {}
    for r in store.records(unit="mgmt", year=year):
        people = set(awaiting_confirmation(r))
        if r.get("status") in EDITABLE_STATUSES:
            people |= set(r.get("author_ids", []))
        for a in people:
            if persons.get(a, {}).get("role") in AUTHOR_ROLES:
                todo.setdefault(a, set()).add(r["id"])
    for pid, ids in sorted(todo.items(), key=lambda x: -len(x[1])):
        pending.append({"id": pid, "name": persons[pid]["display_name"], "role": persons[pid]["role"], "count": len(ids)})
    days_left = None
    if camp and camp.get("deadline"):
        days_left = (dt.date.fromisoformat(camp["deadline"]) - dt.date.today()).days
    attested = store.kv_get(f"attest:{year}", {}) or {}
    authors = {a for r in store.records(unit="mgmt", year=year) for a in r.get("author_ids", []) if persons.get(a, {}).get("role") in AUTHOR_ROLES}
    return {"campaign": camp, "units": rows, "pending": pending, "days_left": days_left, "funnel": funnel("mgmt", year),
            "schedule": [d for d in REMINDER_DAYS], "attested": len(attested.keys() & authors), "authors": len(authors)}


def funnel(unit: str, year: int) -> dict:
    """Кафедра жазбалары қазір қай кезеңде тұр: есепке не кірді, не кіммен кідіріп тұр."""
    rows = store.records(unit=unit, year=year)
    stages = {"Черновики": 0, "На доработке": 0, "У научных руководителей": 0, "У заведующего кафедрой": 0, "У директора": 0, "Согласовано, в отчёте": 0}
    names = {"supervisor": "У научных руководителей", "head": "У заведующего кафедрой", "director": "У директора"}
    waiting = []
    for r in rows:
        status = r.get("status")
        if status == "создано":
            stages["Черновики"] += 1
        elif status == "на доработке":
            stages["На доработке"] += 1
        elif status == store.APPROVED:
            stages["Согласовано, в отчёте"] += 1
        elif status == "на согласовании":
            step = current_step(r)
            stages[names.get((step or {}).get("step"), "У заведующего кафедрой")] += 1
            waiting.append(days_since(r.get("stage_since")))
    return {"stages": [{"label": k, "value": v} for k, v in stages.items()], "approved": stages["Согласовано, в отчёте"], "total": len(rows),
            "not_included": len(rows) - stages["Согласовано, в отчёте"], "longest_wait": max(waiting, default=0)}


def remind(position: dict, unit: str | None, person: str | None, year: int = 2025) -> int:
    camp = store.campaign(year) or {}
    deadline = camp.get("deadline", "")
    sent = 0
    if person:
        store.notify(f"Отчёт НИР за {year} год: у вас есть записи, которые нужно подтвердить или отправить. Срок: {deadline}.", person=person, link="home")
        sent = 1
    elif unit == "mgmt" or not unit:
        status = campaign_status(year)
        for p in status["pending"]:
            store.notify(f"Отчёт НИР за {year} год: записей нужно подтвердить или отправить: {p['count']}. Срок: {deadline}.", person=p["id"], link="home")
            sent += 1
    else:
        store.notify(f"Напоминаем: отчёт НИР за {year} год нужно сдать до {deadline}.", role="responsible", unit=unit, link="report")
        sent = 1
    store.log(position, "Отправлено напоминание", unit or person or "", f"человек: {sent}")
    return sent


# ---------- Жазбаны келісу бағыты ----------

STEP_LABELS = {"supervisor": "Научный руководитель", "head": "Заведующий кафедрой", "director": "Директор"}
STAGE_LABELS = {"supervisor": "У научного руководителя", "head": "У заведующего кафедрой", "director": "У директора"}
REMINDER_DAYS = (14, 7, 3, 1, 0)


def days_since(iso: str | None) -> int:
    if not iso:
        return 0
    try:
        # Белгілер UTC-де жазылады, сондықтан күн де UTC бойынша есептеледі.
        return max(0, (dt.datetime.now(dt.timezone.utc).date() - dt.date.fromisoformat(iso[:10])).days)
    except ValueError:
        return 0


def _positions() -> list[dict]:
    return store.kv_get("positions", []) or []


def is_author(position: dict, rec: dict) -> bool:
    me = position.get("person")
    return me in rec.get("author_ids", []) or me == rec.get("created_by")


def find_supervisor(rec: dict, person: str | None) -> str | None:
    """Жетекші алдымен осы адамның байланысынан, сосын жазбаның өзінен алынады."""
    for s in store.supervisions():
        if s["learner_id"] == person and s["kind"] == "main":
            return s["supervisor_id"]
    for pid in rec.get("supervisor_ids", []):
        if pid != person:
            return pid
    return None


def _valid_supervisor(pid: str | None, rec: dict, learner: str | None) -> str | None:
    """Таңдалған жетекші тек осы кафедраның оқытушысы бола алады."""
    person = store.persons().get(pid or "")
    if person and pid != learner and person.get("role") == "teacher" and person.get("unit") == rec.get("unit"):
        return pid
    return None


def plan_route(rec: dict, submitter: str | None, supervisor_id: str | None = None) -> dict:
    """Бағыт жазбаның авторына қарай құрылады, ал кім енгізгені маңызды емес. Меңгеруші автор болса, директор келіседі."""
    persons = store.persons()
    authors = rec.get("author_ids", [])
    primary = submitter if submitter in authors else next((a for a in authors if persons.get(a, {}).get("role") in AUTHOR_ROLES), submitter)
    steps: list[dict] = []
    needs_supervisor = False
    head = next((p for p in _positions() if p.get("role") == "head" and p.get("unit") == rec.get("unit")), None)
    head_person = head.get("person") if head else None
    if persons.get(primary, {}).get("role") in LEARNERS:
        # Тіркелген жетекші бірінші тұрады, сұраныстағы мән тек ол жоқ кезде және тексерілген соң қабылданады.
        sup = find_supervisor(rec, primary) or _valid_supervisor(supervisor_id, rec, primary)
        if not sup or sup == primary:
            needs_supervisor = True
        elif sup != head_person:
            steps.append({"step": "supervisor", "label": STEP_LABELS["supervisor"], "person": sup, "state": "wait"})
    if head_person and (head_person in authors or head_person == primary):
        steps.append({"step": "director", "label": STEP_LABELS["director"], "role": "director", "state": "wait"})
    else:
        steps.append({"step": "head", "label": STEP_LABELS["head"], "role": "head", "unit": rec.get("unit"), "state": "wait"})
    return {"steps": steps, "needs_supervisor": needs_supervisor}


def current_step(rec: dict) -> dict | None:
    return next((s for s in rec.get("route", []) if s.get("state") == "current"), None)


def stage_text(rec: dict) -> str:
    status = rec.get("status")
    if status == "на согласовании":
        step = current_step(rec)
        return STAGE_LABELS.get((step or {}).get("step"), "На согласовании")
    return {"создано": "Черновик, не отправлен", "на доработке": "Возвращено автору", store.APPROVED: "Согласовано, в отчёте"}.get(status, status or "")


def can_approve(position: dict, rec: dict) -> bool:
    step = current_step(rec)
    if rec.get("status") != "на согласовании" or not step:
        return False
    me, role = position.get("person"), position.get("role")
    # Жетекші шәкіртімен бірге жазған мақаланы келісе алады, ал басқа кезеңде автор өз жазбасын келіспейді.
    if step.get("person") and step["person"] == me:
        return True
    if me in rec.get("author_ids", []):
        return False
    if step.get("role") == role and (role != "head" or position.get("unit") == step.get("unit")):
        return True
    # Жетекші жауап бермесе есеп тоқтап қалмауы үшін меңгеруші оның орнына келісе алады.
    return step.get("step") == "supervisor" and role == "head" and position.get("unit") == rec.get("unit")


def _history(rec: dict, position: dict, action: str, note: str = "") -> None:
    rec.setdefault("history", []).append({"at": store.now(), "by": position.get("label"), "action": action, "note": note})


def _notify_authors(rec: dict, text: str, skip: str | None = None) -> None:
    persons = store.persons()
    targets = set(rec.get("author_ids", [])) | ({rec["created_by"]} if rec.get("created_by") else set())
    for pid in targets:
        if pid != skip and persons.get(pid, {}).get("role") in AUTHOR_ROLES:
            store.notify(text, person=pid, link=f"record/{rec['id']}")


def _notify_step(rec: dict, step: dict) -> None:
    text = f"На согласование: {display_title(rec)[:80]}"
    if step.get("person"):
        store.notify(text, person=step["person"], link=f"record/{rec['id']}")
    else:
        store.notify(text, role=step.get("role"), unit=step.get("unit"), link="approvals")


def submit_record(rid: str, position: dict, supervisor_id: str | None = None, note: str = "") -> dict:
    rec = store.record(rid)
    if not rec:
        return {"error": "Запись не найдена", "code": 404}
    if not is_author(position, rec):
        return {"error": "Отправить запись может только её автор", "code": 403}
    if rec.get("status") not in EDITABLE_STATUSES:
        return {"error": "Запись уже отправлена", "code": 409}
    missing = missing_required(rec["type"], rec.get("fields", {}), rec.get("attrs", {}))
    if missing:
        return {"error": "Заполните: " + ", ".join(m["label"] for m in missing), "missing": missing, "code": 422}
    rec["sections"] = store.compute_sections(rec) or rec.get("sections", [])
    if not rec["sections"]:
        return {"error": NO_SECTION_TEXT, "code": 422}
    plan = plan_route(rec, position.get("person"), supervisor_id)
    if plan["needs_supervisor"]:
        return {"error": "Выберите научного руководителя", "needs_supervisor": True, "code": 409}
    steps = plan["steps"]
    steps[0]["state"] = "current"
    rec["route"] = steps
    rec["status"] = "на согласовании"
    rec["confirmed"] = True
    rec["stage_since"] = store.now()
    chosen = next((s["person"] for s in steps if s["step"] == "supervisor"), None)
    if chosen and chosen not in rec.setdefault("supervisor_ids", []):
        rec["supervisor_ids"].append(chosen)
    _history(rec, position, "Отправлено на согласование", note)
    store.save_record(rec)
    store.log(position, "Запись отправлена на согласование", rid, display_title(rec)[:80])
    _notify_step(rec, steps[0])
    return {"record": rec, "stage": stage_text(rec)}


def approve_record(rid: str, position: dict, note: str = "") -> dict:
    rec = store.record(rid)
    if not rec:
        return {"error": "Запись не найдена", "code": 404}
    if not can_approve(position, rec):
        return {"error": "Эта запись не ждёт вашего согласования", "code": 403}
    step = current_step(rec)
    next_step = next((s for s in rec["route"] if s.get("state") == "wait"), None)
    report_status = store.report_state(rec["unit"], rec["year"])["status"]
    if not next_step and report_status == "на подписании":
        return {"error": "Отчёт уже на подписании. Согласовать запись можно после его возврата на доработку.", "code": 409}
    on_behalf = step.get("step") == "supervisor" and step.get("person") != position.get("person")
    step.update({"state": "done", "at": store.now(), "by": position.get("label"), "on_behalf": on_behalf})
    action = "Согласовано" + (" за научного руководителя" if on_behalf else "")
    _history(rec, position, action, note)
    rec["stage_since"] = store.now()
    if next_step:
        next_step["state"] = "current"
        store.save_record(rec)
        _notify_step(rec, next_step)
        _notify_authors(rec, f"Запись прошла этап «{step['label']}»: {display_title(rec)[:70]}")
    else:
        rec["status"] = store.APPROVED
        rec["approved_at"] = store.now()
        store.save_record(rec)
        if report_status in LOCKED_REPORT_STATUSES:
            _notify_authors(rec, f"Запись согласована: {display_title(rec)[:70]}. Отчёт за этот год уже утверждён, она будет учтена в следующей версии.")
        else:
            _notify_authors(rec, f"Запись согласована и вошла в отчёт: {display_title(rec)[:70]}")
    store.log(position, "Запись согласована", rid, display_title(rec)[:80])
    return {"record": store.record(rid), "stage": stage_text(rec)}


def return_record(rid: str, position: dict, note: str) -> dict:
    rec = store.record(rid)
    if not rec:
        return {"error": "Запись не найдена", "code": 404}
    if not can_approve(position, rec):
        return {"error": "Эта запись не ждёт вашего согласования", "code": 403}
    if not (note or "").strip():
        return {"error": "Напишите, что нужно исправить", "code": 422}
    step = current_step(rec)
    step.update({"state": "returned", "at": store.now(), "by": position.get("label")})
    rec["status"] = "на доработке"
    rec["return_note"] = note.strip()
    rec["stage_since"] = store.now()
    _history(rec, position, "Возвращено на доработку", note.strip())
    store.save_record(rec)
    store.log(position, "Запись возвращена на доработку", rid, note.strip()[:120])
    _notify_authors(rec, f"Запись возвращена на доработку: {display_title(rec)[:60]}. Причина: {note.strip()[:120]}")
    return {"record": store.record(rid), "stage": stage_text(rec)}


def reopen_record(rid: str, position: dict, note: str = "") -> dict:
    """Келісілген жазбаны автор қайта ашады: ол есептен шығып, жаңадан келісуден өтеді."""
    rec = store.record(rid)
    if not rec:
        return {"error": "Запись не найдена", "code": 404}
    if not is_author(position, rec):
        return {"error": "Изменить запись может только её автор", "code": 403}
    if rec.get("status") != store.APPROVED:
        return {"error": "Запись не согласована", "code": 409}
    if store.report_state(rec["unit"], rec["year"])["status"] in LOCKED_REPORT_STATUSES:
        return {"error": "Отчёт уже на подписании. Изменения вносит ответственный по научной работе.", "code": 409}
    rec["status"] = "создано"
    rec["route"] = []
    rec["stage_since"] = store.now()
    _history(rec, position, "Автор открыл запись для изменения", note)
    store.save_record(rec)
    store.log(position, "Запись открыта для изменения", rid, display_title(rec)[:80])
    return {"record": store.record(rid), "stage": stage_text(rec)}


def resolve_claim(rid: str, person: str, accept: bool, position: dict) -> dict:
    """Жауапты соавторлық туралы өтінішті шешеді. Қабылданса, жазба бөлімдері қайта есептеледі."""
    rec = store.record(rid)
    if not rec or person not in rec.get("claims", []):
        return {"error": "Заявка не найдена", "code": 404}
    rec["claims"].remove(person)
    persons = store.persons()
    name = persons.get(person, {}).get("display_name", person)
    if accept:
        rec["author_ids"].append(person)
        role = persons.get(person, {}).get("role")
        if role in AUTHOR_ROLES and role not in rec.get("roles", []):
            rec.setdefault("roles", []).append(role)
        rec["sections"] = store.compute_sections(rec) or rec.get("sections", [])
    _history(rec, position, f"Соавтор {name}: " + ("добавлен" if accept else "отклонён"))
    store.save_record(rec)
    store.notify(f"Заявка на соавторство {'принята' if accept else 'отклонена'}: {display_title(rec)[:70]}", person=person, link="home")
    store.log(position, "Рассмотрена заявка на соавторство", rid, "принята" if accept else "отклонена")
    return {"record": rec, "stage": stage_text(rec)}


def apply_published(rid: str, fields: dict, position: dict) -> dict:
    """Шыққан мақаланың беті мен нөмірін Crossref-тен жаңартады: дерек ресми болғандықтан қайта келісу керек емес."""
    rec = store.record(rid)
    for key in ("pages", "issue", "doi", "year"):
        if fields.get(key):
            rec["fields"][key] = fields[key]
    rec["year"] = _year(rec["fields"], rec.get("year"))
    rec["in_press"] = False
    _history(rec, position, "Выходные данные обновлены из Crossref")
    store.save_record(rec)
    store.log(position, "Выходные данные обновлены из Crossref", rid)
    return rec


def precheck(rec: dict, rows: list[dict] | None = None) -> dict:
    """Келісушіге арналған алдын ала тексеру: жазбаны ашпай-ақ неге назар аудару керегін көрсетеді."""
    from .reporting import evidence_need

    rows = rows if rows is not None else store.records(unit=rec.get("unit"), year=rec.get("year"))
    reasons: list[dict] = []
    coll = validators.check_collection(rows).get(rec["id"], [])
    for issue in validators.check_record(rec, settings().get("journal_watchlist")) + coll:
        if issue["level"] in ("error", "warn") and issue["code"] not in rec.get("dismissed", []):
            reasons.append({"level": issue["level"], "text": issue["text"]})
    needs = sorted({evidence_need(s) for s in rec.get("sections", [])} - {None})
    if needs and not rec.get("evidence"):
        reasons.append({"level": "warn", "text": "Нет подтверждающего документа: " + ", ".join(needs)})
    other = find_existing(rec.get("fields", {}), exclude=rec["id"])
    if other:
        reasons.append({"level": "warn", "text": f"Похожая запись уже есть: {display_title(other)[:70]}"})
    ai = rec.get("ai") or {}
    labels = {f["key"]: f["label"] for f in TYPES.get(rec["type"], {}).get("fields", [])}
    unverified = [labels.get(k, k) for k, v in (ai.get("checks") or {}).items() if v == "unverified" and k in labels]
    if unverified:
        reasons.append({"level": "warn", "text": "Не подтверждены документом: " + ", ".join(unverified)})
    for m in ai.get("mismatches") or []:
        reasons.append({"level": "warn", "text": f"Расхождение с Crossref, {labels.get(m['key'], m['key'])}: «{m['value']}» и «{m['crossref']}»"})
    verified = sorted({v for v in (ai.get("checks") or {}).values() if v != "unverified"})
    good = []
    if "crossref" in verified:
        good.append("данные подтверждены Crossref")
    if "document" in verified:
        good.append("поля найдены в документе")
    if rec.get("evidence"):
        good.append("документ приложен")
    level = "error" if any(r["level"] == "error" for r in reasons) else "warn" if reasons else "ok"
    return {"level": level, "reasons": reasons, "good": good}


def item_view(rec: dict, position: dict, persons: dict, rows: list[dict] | None = None) -> dict:
    from .reporting import evidence_need

    authors = [persons[a]["display_name"] for a in rec.get("author_ids", []) if a in persons] + rec.get("external_authors", [])
    index = rec.get("attrs", {}).get("index")
    return {"id": rec["id"], "title": display_title(rec), "type": rec["type"], "type_label": TYPES[rec["type"]]["label"], "index": index, "year": rec.get("year"),
            "sections": rec.get("sections", []), "status": rec.get("status"), "stage": stage_text(rec), "days": days_since(rec.get("stage_since")),
            "authors": authors[:4], "authors_more": max(0, len(authors) - 4), "return_note": rec.get("return_note") if rec.get("status") == "на доработке" else None,
            "route": [{"label": s["label"], "state": s["state"]} for s in rec.get("route", [])], "in_report": rec.get("status") == store.APPROVED,
            "has_evidence": bool(rec.get("evidence")), "evidence_need": sorted({evidence_need(s) for s in rec.get("sections", [])} - {None}),
            "missing": [m["label"] for m in missing_required(rec["type"], rec.get("fields", {}), rec.get("attrs", {}))] + ([] if rec.get("sections") else ["раздел отчёта"]),
            "can_submit": is_author(position, rec) and rec.get("status") in EDITABLE_STATUSES, "confirmed": bool(rec.get("confirmed")),
            "needs_confirm": position.get("person") in awaiting_confirmation(rec)}


def flow_view(rec: dict, position: dict) -> dict:
    """Жазба панеліне: бағыт, тарих, тексеру нәтижесі және қазір қолжетімді әрекеттер."""
    actions = []
    if rec.get("status") in EDITABLE_STATUSES and is_author(position, rec):
        actions.append("submit")
    if can_approve(position, rec):
        actions += ["approve", "return"]
    if rec.get("status") == store.APPROVED and is_author(position, rec):
        actions.append("reopen")
        if rec.get("in_press"):
            actions.append("check")
    if position.get("person") in awaiting_confirmation(rec):
        actions.append("confirm")
    plan = plan_route(rec, position.get("person")) if "submit" in actions else None
    route = rec.get("route") or (plan["steps"] if plan else [])
    persons = store.persons()
    claims = []
    if position.get("role") in ("responsible", "head"):
        claims = [{"id": p, "name": persons.get(p, {}).get("display_name", p)} for p in rec.get("claims", [])]
    return {"status": rec.get("status"), "stage": stage_text(rec), "days": days_since(rec.get("stage_since")), "actions": actions, "claims": claims,
            "route": [{"label": s["label"], "state": s["state"], "at": s.get("at"), "on_behalf": s.get("on_behalf", False)} for s in route],
            "history": rec.get("history", []), "needs_supervisor": bool(plan and plan["needs_supervisor"]),
            "precheck": precheck(rec), "return_note": rec.get("return_note") if rec.get("status") == "на доработке" else None,
            "in_report": rec.get("status") == store.APPROVED}


def pipeline(position: dict, year: int = 2025) -> dict:
    """Автордың жеке беті: әр нәтиже қай кезеңде тұр және енді не істеу керек."""
    me = position.get("person")
    persons = store.persons()
    rows = [r for r in store.records() if me in r.get("author_ids", []) or r.get("created_by") == me]
    rows.sort(key=lambda r: (r.get("status") == store.APPROVED, r.get("updated_at", "")), reverse=False)
    items = [item_view(r, position, persons) for r in rows]
    counts = {"создано": 0, "на доработке": 0, "на согласовании": 0, store.APPROVED: 0}
    for i in items:
        counts[i["status"]] = counts.get(i["status"], 0) + 1
    camp = store.campaign(year) or {}
    days_left = (dt.date.fromisoformat(camp["deadline"]) - dt.date.today()).days if camp.get("deadline") else None
    attested = store.kv_get(f"attest:{year}", {}) or {}
    in_year = sum(1 for r in rows if r.get("year") == year and r.get("status") == store.APPROVED)
    return {"items": items, "counts": counts, "campaign": {"title": camp.get("title"), "deadline": camp.get("deadline"), "days_left": days_left},
            "attested_at": attested.get(me), "year": year, "in_report": in_year, "found": len(store.candidates(person=me)),
            "unconfirmed": sum(1 for r in rows if me in awaiting_confirmation(r))}


def attest_list(position: dict, year: int = 2025) -> dict:
    attested = store.kv_get(f"attest:{year}", {}) or {}
    attested[position.get("person")] = store.now()
    store.kv_set(f"attest:{year}", attested)
    store.log(position, "Автор подтвердил свой список за год", str(year))
    return {"attested_at": attested[position.get("person")]}


def inbox(position: dict) -> list[dict]:
    """Қазір осы адамның келісуін күтіп тұрған жазбалар."""
    persons = store.persons()
    out = []
    rows = store.records()
    pending = [r for r in rows if can_approve(position, r)]
    for r in pending:
        item = item_view(r, position, persons)
        item["precheck"] = precheck(r, [x for x in rows if x.get("unit") == r.get("unit") and x.get("year") == r.get("year")])
        step = current_step(r) or {}
        item["step"] = step.get("label")
        item["on_behalf"] = step.get("step") == "supervisor" and step.get("person") != position.get("person")
        out.append(item)
    out.sort(key=lambda x: (-x["days"], x["id"]))
    return out


def approve_many(ids: list[str], position: dict) -> dict:
    done, skipped = 0, 0
    for rid in ids:
        result = approve_record(rid, position)
        if result.get("error"):
            skipped += 1
        else:
            done += 1
    return {"approved": done, "skipped": skipped}


def remind_all(position: dict, year: int = 2025, automatic: bool = False) -> dict:
    """Әркімге өз ісін еске салады: авторға черновик, келісушіге кезек, жауаптыға есеп."""
    camp = store.campaign(year) or {}
    deadline = camp.get("deadline", "")
    persons = store.persons()
    rows = store.records(unit="mgmt", year=year)
    sent = {"authors": 0, "approvers": 0, "responsible": 0}
    per_author: dict[str, dict] = {}
    for r in rows:
        for a in r.get("author_ids", []):
            if persons.get(a, {}).get("role") not in AUTHOR_ROLES:
                continue
            bucket = per_author.setdefault(a, {"drafts": 0, "returned": 0, "confirm": 0})
            if r.get("status") == "создано":
                bucket["drafts"] += 1
            elif r.get("status") == "на доработке":
                bucket["returned"] += 1
            if a in awaiting_confirmation(r):
                bucket["confirm"] += 1
    for pid, b in per_author.items():
        parts = []
        if b["drafts"]:
            parts.append(f"не отправлено записей: {b['drafts']}")
        if b["returned"]:
            parts.append(f"возвращено на доработку: {b['returned']}")
        if b["confirm"]:
            parts.append(f"ждут подтверждения: {b['confirm']}")
        if parts:
            store.notify(f"Отчёт НИР за {year} год, срок {deadline}: " + ", ".join(parts) + ".", person=pid, link="home")
            sent["authors"] += 1
    per_step: dict[str, int] = {}
    per_role: dict[tuple, int] = {}
    for r in rows:
        step = current_step(r) if r.get("status") == "на согласовании" else None
        if step and step.get("person"):
            per_step[step["person"]] = per_step.get(step["person"], 0) + 1
        elif step:
            key = (step.get("role"), step.get("unit"))
            per_role[key] = per_role.get(key, 0) + 1
    for pid, n in per_step.items():
        store.notify(f"Отчёт НИР за {year} год, срок {deadline}: на вашем согласовании записей: {n}.", person=pid, link="approvals")
        sent["approvers"] += 1
    for (role, unit), n in per_role.items():
        store.notify(f"Отчёт НИР за {year} год, срок {deadline}: на вашем согласовании записей: {n}.", role=role, unit=unit, link="approvals")
        sent["approvers"] += 1
    state = store.report_state("mgmt", year)
    if state["status"] in EDITABLE_STATUSES:
        q = review_queue("mgmt", year)
        store.notify(f"Отчёт НИР за {year} год, срок {deadline}: проверьте перечень (замечаний: {len(q['items'])}) и отправьте на согласование.",
                     role="responsible", unit="mgmt", link="report")
        sent["responsible"] = 1
    store.log(position, "Напоминания разосланы автоматически" if automatic else "Напоминания разосланы", str(year), str(sent))
    return {**sent, "sent": sum(sent.values())}


def campaign_tick(today: dt.date | None = None, year: int = 2025) -> dict | None:
    """Мерзімге 14, 7, 3, 1 күн және сол күні бір реттен еске салады."""
    today = today or dt.date.today()
    camp = store.campaign(year)
    if not camp or not camp.get("deadline"):
        return None
    left = (dt.date.fromisoformat(camp["deadline"]) - today).days
    key = f"reminded:{year}:{today.isoformat()}"
    if left not in REMINDER_DAYS or store.kv_get(key):
        return None
    store.kv_set(key, True)
    return remind_all({"person": "", "label": "Система", "role": "system"}, year, automatic=True)

"""Аналитика: кафедра, жоғары мектеп, университет, ғылыми жетекшілік, 29 қорытынды көрсеткіш."""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from . import store, validators
from .names import is_kazakh

PUB_TYPES = ("article", "conference", "monograph")
LEARNERS = ("student", "master", "doctoral")

SDG_KEYWORDS = {
    "ЦУР 2": r"food|продоволь|азық|аграр|agri|ауыл шаруашы|сельск|wheat",
    "ЦУР 4": r"educat|образован|білім|университет|жоо|вуз",
    "ЦУР 7": r"energy|энерг|renewable",
    "ЦУР 8": r"employment|занятост|еңбек|рынок труда|economic growth|жұмыспен|кәсіпкер|business",
    "ЦУР 9": r"innovat|инновац|industr|индустр|цифр|digital|искусственн|жасанды интеллект|artificial",
    "ЦУР 10": r"inequal|неравенств|теңсіз|инклюзив|inclusive",
    "ЦУР 11": r"өңір|region|регион|тұрғын|urban",
    "ЦУР 12": r"waste|отход|қалдық|esg|устойчив|sustainab|тұрақты",
    "ЦУР 13": r"co2|climate|климат|green|жасыл|зелен",
    "ЦУР 16": r"corruption|жемқорлық|коррупц|мемлекеттік басқару|governance|государственн",
}


def sdg_tags(text: str) -> list[str]:
    low = (text or "").lower()
    return [k for k, rx in SDG_KEYWORDS.items() if re.search(rx, low)]


def unit_tree() -> dict:
    units = store.units()
    children = defaultdict(list)
    for u in units.values():
        if u.get("parent"):
            children[u["parent"]].append(u["id"])
    return {"units": units, "children": children}


def descendants(unit_id: str, tree: dict | None = None) -> list[str]:
    tree = tree or unit_tree()
    out, stack = [], [unit_id]
    while stack:
        cur = stack.pop()
        out.append(cur)
        stack.extend(tree["children"].get(cur, []))
    return out


def overview_for(records: list[dict]) -> dict:
    c = Counter()
    prize_people = defaultdict(set)
    for r in records:
        t, roles, attrs = r["type"], r.get("roles", []), r.get("attrs", {})
        c[f"type_{t}"] += 1
        if t == "article":
            idx = attrs.get("index")
            c[idx] += 1
            if "teacher" in roles:
                c[f"pps_{idx}"] += 1
            if idx in ("wos", "scopus"):
                q = (r["fields"].get("quartile") or "").upper()
                if re.search(r"Q[12]\b|КВАРТИЛЬ\s*Q[12]", q):
                    c[f"{idx}_q12"] += 1
        if t == "conference":
            c[f"conference_{attrs.get('place', 'kz')}"] += 1
            if "teacher" in roles:
                c["pps_conference"] += 1
        if t in PUB_TYPES:
            if "teacher" in roles:
                c["pps_pubs"] += 1
            for role in LEARNERS:
                if role in roles:
                    c[f"{role}_pubs"] += 1
            if any(x in roles for x in LEARNERS):
                c["learner_pubs"] += 1
        if t == "prize":
            for role in roles:
                prize_people[role].update(r.get("author_ids", []))
            c["prize_rows"] += 1
    c["prize_people"] = len(set().union(*prize_people.values())) if prize_people else 0
    for role in LEARNERS:
        c[f"{role}_prize_people"] = len(prize_people.get(role, set()))
    return dict(c)


def active_records(unit: str = "mgmt", year: int | None = 2025) -> list[dict]:
    return store.records(unit=unit, year=year, approved_only=True)


def indicators(unit: str = "mgmt", year: int = 2025) -> list[dict]:
    """Нысанның 6-бөлімі. source: auto — жазбалардан, staff — штат санымен, manual — адам енгізеді."""
    rows = active_records(unit, year)
    ov = overview_for(rows)
    manual = store.kv_get(f"manual:{unit}:{year}", {}) or {}
    staff = manual.get("staff_count") or 0
    columns = store.kv_get("analysis_columns", {}) or {}
    pps = [r for r in rows if "teacher" in r.get("roles", []) and r["type"] in PUB_TYPES]
    koksnvo = [r for r in pps if r["attrs"].get("index") == "koksnvo"]
    non_koksnvo = [r for r in pps if r["type"] != "monograph" and r["attrs"].get("index") != "koksnvo" and
                   r["attrs"].get("index") not in ("wos", "scopus")]
    kk_k = [r for r in koksnvo if is_kazakh(r["fields"].get("title"))]
    kk_n = [r for r in non_koksnvo if is_kazakh(r["fields"].get("title"))]
    awards = ov.get("type_award", 0)
    wos_q12 = ov.get("wos_q12", 0)
    teachers_ws = set()
    all_persons = store.persons()
    for r in pps:
        if r["attrs"].get("index") in ("wos", "scopus"):
            for a in r.get("author_ids", []):
                if all_persons.get(a, {}).get("role") == "teacher":
                    teachers_ws.add(a)
    reported = lambda row: columns.get(str(row), {}).get("reported")  # noqa: E731
    share = lambda a, b: round(a / b, 3) if b else None  # noqa: E731
    defs = [
        (3, "Общее количество наград", awards, "auto"),
        (4, "Остепененность кадров (в %)", manual.get("degree_share"), "manual"),
        (5, "Общее количество публикаций ППС:", ov.get("pps_pubs", 0), "auto"),
        (6, "из них в Web of Science", ov.get("pps_wos", 0), "auto"),
        (7, "Среднее количество публикаций в изданиях, входящих в перечень КОКСНВО МНВО РК, на одного преподавателя",
         share(len(koksnvo), staff), "staff"),
        (8, "Доля опубликованных научных статей на государственном языке: - в других отечественных научных журналах",
         share(len(kk_n), ov.get("pps_pubs", 0)), "auto"),
        (9, "Доля опубликованных научных статей на государственном языке: - в научных изданиях, рекомендуемых КОКСОН МНВО РК",
         share(len(kk_k), ov.get("pps_pubs", 0)), "auto"),
        (10, "Доля зарубежных ученых и преподавателей, привлеченных для ведения совместных исследований и чтения лекций от общего числа ППС",
         manual.get("foreign_scholar_share"), "manual"),
        (11, "Среднее количество публикаций в высокорейтинговых изданиях Q1, Q2 Journal Citation Reports JCR на одного работника",
         share(wos_q12, staff), "staff"),
        (12, "Количество статей Q1Q2", wos_q12, "auto"),
        (13, "Scopus", ov.get("pps_scopus", 0), "auto"),
        (14, "КОКСНВО МНВО РК", len(koksnvo), "auto"),
        (15, "КОКСНВО МНВО РК на казахском языке", len(kk_k), "auto"),
        (16, "не КОКСНВО МНВО РК", len(non_koksnvo), "auto"),
        (17, "не КОКСНВО МНВО РК на казахском языке", len(kk_n), "auto"),
        (18, "c представителями казахстанских ОВПО", _tagged(pps, "coauthor_kz", reported(18)), "auto"),
        (19, "с представителями зарубежных ОВПО, научных организаций", _tagged(pps, "coauthor_foreign", reported(19)), "auto"),
        (20, "с представителями бизнес-партнерств, промышленности", _tagged(pps, "coauthor_business", reported(20)), "auto"),
        (21, "по ЦУР", _tagged(pps, "sdg", reported(21)), "auto"),
        (22, "Доля ППС, публикующих статьи в журналах, входящих в Web of Science и в Scopus (в %)", share(len(teachers_ws), staff), "staff"),
        (23, "Общее количество публикаций обучающихся:", ov.get("learner_pubs", 0), "auto"),
        (24, "из них публикации студентов:", ov.get("student_pubs", 0), "auto"),
        (25, "магистрантов:", ov.get("master_pubs", 0), "auto"),
        (26, "докторантов:", ov.get("doctoral_pubs", 0), "auto"),
        (27, "Общее количество обучающихся, победивших на республиканских и международных конкурсах  научных проектов:", ov.get("prize_people", 0), "auto"),
        (28, "из них студенты:", ov.get("student_prize_people", 0), "auto"),
        (29, "магистранты:", ov.get("master_prize_people", 0), "auto"),
        (30, "докторанты:", ov.get("doctoral_prize_people", 0), "auto"),
        (31, "Финансирование НИР (в тыс. тенге)", manual.get("funding"), "manual"),
    ]
    out = []
    for row, label, value, source in defs:
        col = columns.get(str(row), {})
        out.append({"row": row, "label": label, "value": value, "source": source, "note": manual.get("funding_note", "") if row == 31 else "",
                    "prev": col.get("prev", ""), "reported": col.get("reported", "") if year == 2025 else ""})
    return out


def overview(unit: str = "mgmt", year: int = 2025) -> dict:
    rows = active_records(unit, year)
    all_rows = store.records(unit=unit, year=year, include_merged=True, approved_only=True)
    ov = overview_for(rows)
    prev_cols = store.kv_get("analysis_columns", {}) or {}
    cards = [
        {"key": "scopus", "label": "Scopus", "value": ov.get("scopus", 0), "pps": ov.get("pps_scopus", 0), "prev": _num(prev_cols.get("13", {}).get("prev"))},
        {"key": "wos", "label": "Web of Science", "value": ov.get("wos", 0), "pps": ov.get("pps_wos", 0), "prev": _num(prev_cols.get("6", {}).get("prev"))},
        {"key": "koksnvo", "label": "КОКСНВО", "value": ov.get("koksnvo", 0), "pps": ov.get("pps_koksnvo", 0), "prev": _num(prev_cols.get("14", {}).get("prev"))},
        {"key": "conference", "label": "Конференции", "value": ov.get("type_conference", 0), "prev": None},
        {"key": "monograph", "label": "Монографии", "value": ov.get("type_monograph", 0), "prev": None},
        {"key": "learner_pubs", "label": "Публикации обучающихся", "value": ov.get("learner_pubs", 0), "prev": _num(prev_cols.get("23", {}).get("prev"))},
        {"key": "prize_people", "label": "Призёры", "value": ov.get("prize_people", 0), "prev": _num(prev_cols.get("27", {}).get("prev"))},
        {"key": "type_award", "label": "Награды", "value": ov.get("type_award", 0), "prev": _num(prev_cols.get("3", {}).get("prev"))},
    ]
    by_type = [{"type": k[5:], "value": v} for k, v in ov.items() if k.startswith("type_")]
    by_role = [
        {"role": "Преподаватели", "value": ov.get("pps_pubs", 0)},
        {"role": "Докторанты", "value": ov.get("doctoral_pubs", 0)},
        {"role": "Магистранты", "value": ov.get("master_pubs", 0)},
        {"role": "Студенты", "value": ov.get("student_pubs", 0)},
    ]
    return {"unit": unit, "year": year, "cards": cards, "by_type": by_type, "by_role": by_role, "raw": ov,
            "rows_total": len(all_rows), "rows_unique": len(rows),
            "not_confirmed": sum(1 for r in rows if not r.get("confirmed")),
            "in_press": sum(1 for r in rows if r.get("in_press"))}


def _tagged(rows: list[dict], key: str, reported=None) -> int | None:
    """Белгіні агент мақаладан қояды. Белгі әлі жоқ болса, сан шығарылмайды, ал бұрынғы белгісіз жолдардың саны нысандағы мәннен алынады."""
    tagged = [r for r in rows if key in r.get("attrs", {})]
    if not tagged:
        return None
    count = sum(1 for r in tagged if r["attrs"].get(key))
    return count if len(tagged) == len(rows) else count + int(_num(reported) or 0)


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def teachers_table(unit: str = "mgmt", year: int = 2025) -> list[dict]:
    rows = active_records(unit, year)
    persons = store.persons()
    sup = store.supervisions()
    out = []
    pubs_by_person = defaultdict(list)
    for r in rows:
        for a in r.get("author_ids", []):
            pubs_by_person[a].append(r)
    for pid, p in persons.items():
        if p["role"] != "teacher" or p.get("unit") != unit:
            continue
        mine = pubs_by_person.get(pid, [])
        c = Counter()
        for r in mine:
            if r["type"] == "article":
                c[r["attrs"].get("index")] += 1
            else:
                c[r["type"]] += 1
        learners = [s for s in sup if s["supervisor_id"] == pid]
        level = Counter(persons.get(s["learner_id"], {}).get("role") for s in learners)
        learner_ids = {s["learner_id"] for s in learners}
        learner_pubs = {r["id"] for r in rows if r["type"] in PUB_TYPES and (set(r.get("author_ids", [])) & learner_ids)}
        out.append({
            "id": pid, "name": p["display_name"], "degree": p.get("degree", ""), "scopus": c.get("scopus", 0), "wos": c.get("wos", 0),
            "koksnvo": c.get("koksnvo", 0), "conference": c.get("conference", 0), "monograph": c.get("monograph", 0),
            "students": level.get("student", 0), "masters": level.get("master", 0), "doctorals": level.get("doctoral", 0),
            "learner_pubs": len(learner_pubs), "total": len([r for r in mine if r["type"] in PUB_TYPES]),
            "unconfirmed": sum(1 for r in mine if not r.get("confirmed") and pid in (r.get("pending_for") or r.get("author_ids", []))),
            "has_data": bool(mine or learners),
        })
    # Есепте жазбасы жоқ адамның аты шығарылмайды: бір есептен «жарияланымы жоқ» деген қорытынды шықпайды.
    return sorted((x for x in out if x["has_data"]), key=lambda x: (-x["total"], x["name"]))


def portal_count(unit: str = "mgmt") -> int:
    return sum(1 for p in store.persons().values() if p.get("unit") == unit and p.get("on_portal") and p["role"] == "teacher")


def supervision_table(unit: str = "mgmt", year: int = 2025, supervisor: str | None = None) -> dict:
    rows = active_records(unit, year)
    persons = store.persons()
    sup = store.supervisions()
    pubs = defaultdict(list)
    for r in rows:
        for a in r.get("author_ids", []):
            pubs[a].append(r)
    groups = defaultdict(list)
    linked = set()
    for s in sup:
        learner = persons.get(s["learner_id"])
        boss = persons.get(s["supervisor_id"])
        if not learner or not boss or learner.get("unit") != unit:
            continue
        linked.add(s["learner_id"])
        if supervisor and s["supervisor_id"] != supervisor:
            continue
        mine = pubs.get(s["learner_id"], [])
        groups[s["supervisor_id"]].append({
            "learner_id": s["learner_id"], "learner": learner["display_name"], "level": learner["role"],
            "group": learner.get("group", ""), "kind": s["kind"],
            "scopus": sum(1 for r in mine if r["attrs"].get("index") in ("scopus", "wos")),
            "koksnvo": sum(1 for r in mine if r["attrs"].get("index") == "koksnvo"),
            "conference": sum(1 for r in mine if r["type"] == "conference"),
            "prizes": sum(1 for r in mine if r["type"] == "prize"),
            "total": len(mine),
        })
    result = []
    for sid, items in groups.items():
        boss = persons[sid]
        items.sort(key=lambda x: ({"doctoral": 0, "master": 1, "student": 2}.get(x["level"], 3), x["learner"]))
        result.append({"supervisor_id": sid, "supervisor": boss["display_name"], "external": boss["role"] == "external",
                       "count": len(items), "students": sum(1 for i in items if i["level"] == "student"),
                       "masters": sum(1 for i in items if i["level"] == "master"),
                       "doctorals": sum(1 for i in items if i["level"] == "doctoral"),
                       "pubs": sum(i["total"] for i in items), "learners": items})
    result.sort(key=lambda g: (g["external"], -g["count"], g["supervisor"]))
    missing = [{"id": pid, "name": p["display_name"], "level": p["role"], "group": p.get("group", ""), "total": len(pubs.get(pid, []))}
               for pid, p in persons.items() if p["role"] in LEARNERS and p.get("unit") == unit and pid not in linked]
    return {"groups": result, "missing": sorted(missing, key=lambda x: (x["level"], x["name"])), "linked": len(linked)}


def compare(parent: str, year: int = 2025) -> dict:
    """Бөлімшелерді салыстыру. Менеджменттен басқа сандар сынақ деректері."""
    tree = unit_tree()
    units = tree["units"]
    stats = store.kv_get("unit_stats", {}) or {}
    shared = store.kv_get("shared_between_departments", {}) or {}
    rows = []
    for uid in tree["children"].get(parent, []):
        u = units[uid]
        row = _unit_numbers(uid, year, tree, stats, shared)
        state = store.report_state(uid, year) if u["kind"] == "department" else {}
        row.update({"id": uid, "name": u["name"], "kind": u["kind"], "synthetic": bool(u.get("synthetic")),
                    "status": state.get("status", ""), "has_children": bool(tree["children"].get(uid))})
        rows.append(row)
    rows.sort(key=lambda r: -r["scopus"])
    total = _unit_numbers(parent, year, tree, stats, shared)
    summed = {k: sum(r.get(k, 0) for r in rows) for k in ("scopus", "wos", "koksnvo", "conference", "monograph", "learner_pubs", "prizes")}
    return {"parent": parent, "parent_name": units[parent]["name"], "rows": rows, "total": total, "summed": summed,
            "shared": shared.get(parent, 0), "children_count": len(rows)}


def _unit_numbers(uid: str, year: int, tree: dict, stats: dict, shared: dict) -> dict:
    keys = ("scopus", "wos", "koksnvo", "conference", "monograph", "learner_pubs", "prizes", "staff")
    children = tree["children"].get(uid, [])
    if children:
        parts = [_unit_numbers(c, year, tree, stats, shared) for c in children]
        out = {k: sum(p[k] for p in parts) for k in keys}
        drop = shared.get(uid, 0)
        out["scopus"] = max(0, out["scopus"] - drop)
        out["prev_scopus"] = sum(p.get("prev_scopus") or 0 for p in parts)
        return out
    if uid == "mgmt":
        ov = overview_for(active_records("mgmt", year))
        manual = store.kv_get(f"manual:mgmt:{year}", {}) or {}
        prev = _num((store.kv_get("analysis_columns", {}) or {}).get("13", {}).get("prev")) or 0
        return {"scopus": ov.get("scopus", 0), "wos": ov.get("wos", 0), "koksnvo": ov.get("koksnvo", 0),
                "conference": ov.get("type_conference", 0), "monograph": ov.get("type_monograph", 0),
                "learner_pubs": ov.get("learner_pubs", 0), "prizes": ov.get("prize_people", 0),
                "staff": manual.get("staff_count", 0), "prev_scopus": prev}
    s = stats.get(uid, {})
    return {"scopus": s.get("scopus", 0), "wos": s.get("wos", 0), "koksnvo": s.get("koksnvo", 0), "conference": s.get("conference", 0),
            "monograph": s.get("monograph", 0), "learner_pubs": s.get("learner_pubs", 0), "prizes": s.get("prizes", 0),
            "staff": s.get("staff", 0), "prev_scopus": s.get("prev_scopus", 0)}


def plan_fact(unit: str = "mgmt", year: int = 2025) -> list[dict]:
    plan = store.kv_get(f"plan:{unit}:{year}", {}) or {}
    ov = overview_for(active_records(unit, year))
    labels = {"scopus": "Scopus", "wos": "Web of Science", "koksnvo": "КОКСНВО", "monograph": "Монографии",
              "learner_pubs": "Публикации обучающихся", "prizes": "Призёры"}
    fact = {"scopus": ov.get("scopus", 0), "wos": ov.get("wos", 0), "koksnvo": ov.get("koksnvo", 0),
            "monograph": ov.get("type_monograph", 0), "learner_pubs": ov.get("learner_pubs", 0), "prizes": ov.get("prize_people", 0)}
    out = []
    for k, label in labels.items():
        target = plan.get(k, 0)
        out.append({"key": k, "label": label, "plan": target, "fact": fact.get(k, 0),
                    "percent": round(fact.get(k, 0) * 100 / target) if target else None,
                    "gap": target - fact.get(k, 0)})
    return out


def risks(unit: str = "mgmt", year: int = 2025) -> dict:
    settings = store.kv_get("settings", {}) or {}
    req = settings.get("doctoral_requirements", {})
    persons = store.persons()
    rows = active_records(unit, year)
    all_years = store.records(unit=unit, approved_only=True)
    sup = store.supervisions()
    doctoral = []
    for pid, p in persons.items():
        if p["role"] != "doctoral" or p.get("unit") != unit:
            continue
        mine = [r for r in all_years if pid in r.get("author_ids", []) and r.get("confirmed", True)]
        have = {
            "scopus_or_wos": sum(1 for r in mine if r["attrs"].get("index") in ("scopus", "wos")),
            "koksnvo": sum(1 for r in mine if r["attrs"].get("index") == "koksnvo"),
            "conference": sum(1 for r in mine if r["type"] == "conference"),
        }
        gaps = {k: max(0, int(req.get(k, 0)) - v) for k, v in have.items()}
        bosses = [persons[s["supervisor_id"]]["display_name"] for s in sup
                  if s["learner_id"] == pid and s["supervisor_id"] in persons]
        doctoral.append({"id": pid, "name": p["display_name"], "group": p.get("group", ""), "have": have, "gaps": gaps,
                         "ready": not any(gaps.values()), "supervisors": bosses})
    doctoral.sort(key=lambda d: (d["ready"], -sum(d["gaps"].values()), d["name"]))
    watch = settings.get("journal_watchlist", [])
    flagged = []
    for r in rows:
        for iss in validators.check_record(r, watch):
            if iss["code"] == "JOURNAL_RISK":
                flagged.append({"id": r["id"], "title": r["fields"].get("title", ""), "source": r["fields"].get("source", ""), "reason": iss["text"]})
    return {"doctoral": doctoral, "requirements": req, "journals": flagged, "watchlist": watch}

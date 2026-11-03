"""Кафедра есебі мен ашық дереккөздерден демо-дерек жасайды.

Нақты болатыны: кафедра оқытушылары (ашық портфолио беттері), жарияланған еңбектердің авторлары және
есептегі жүлдегер білім алушылар. Қосылмайтыны: телефон мен email, жүлде жолдарында олардың орнына
ешкімге жетпейтін сынақ мәні тұрады. Нақты адамдарға жасанды дәреже, топ, расталмаған мәртебе немесе
ойдан шығарылған жарияланым тағылмайды.

Қолданылуы:  python tools/build_seed.py "<есеп.xlsx>"
"""
from __future__ import annotations

import datetime as dt
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from anonymize_seed import anonymize  # noqa: E402
from app.catalog import attrs_from_block, route  # noqa: E402
from app.form_parser import read_blocks, schema_only  # noqa: E402
from app.names import parse_people, same_person, split_authors_supervisor, translit  # noqa: E402

RNG = random.Random(605)

# Демоны жасаушы өз жазбаларын көрсетеді, сондықтан докторант рөлі тек осы адамға атымен бекітілген.
OWNER_SURNAME = "Муратбеков"
OWNER_GROUP = "D072-4117-26-01"

# Ойдан жасалған үлгі дипломдағы адам. Кафедра тізімдеріне кірмейді.
SAMPLE_STUDENT = {"id": "sample1", "display_name": "Ульгиева А.Б.", "display_latin": "Ulgiyeva A.B.", "full_name": "", "role": "student", "unit": None,
                  "aliases": ["Ульгиева А.Б.", "Ulgiyeva A.B."], "group": "МН-31", "degree": "", "position": "", "orcid": "", "phone": "", "email": "",
                  "on_portal": False, "sample": True}

UNITS = [
    {"id": "uni", "name": "ЕНУ им. Л.Н. Гумилева", "kind": "university", "parent": None},
    {"id": "vshet", "name": "Высшая школа экономики и туризма", "kind": "school", "parent": "uni",
     "names_by_year": {"2025": "Экономический факультет"}, "head_title": "Директор"},
    {"id": "mgmt", "name": "Менеджмент", "kind": "department", "parent": "vshet"},
    {"id": "audit", "name": "Государственный аудит", "kind": "department", "parent": "vshet", "synthetic": True},
    {"id": "tourism", "name": "Туризм", "kind": "department", "parent": "vshet", "synthetic": True},
    {"id": "acc", "name": "Учет и анализ", "kind": "department", "parent": "vshet", "synthetic": True},
    {"id": "fin", "name": "Финансы", "kind": "department", "parent": "vshet", "synthetic": True},
    {"id": "econ", "name": "Экономика и предпринимательство", "kind": "department", "parent": "vshet", "synthetic": True},
]
TOP_UNITS = [
    ("edu", "Высшая школа образования", "school"),
    ("jour", "Высшая школа журналистики и социальных наук", "school"),
    ("dsai", "Институт цифровых наук и ИИ", "institute"),
    ("nat", "Институт естественных наук", "institute"),
    ("phys", "Институт физико-технических наук", "institute"),
    ("cont", "Институт непрерывного образования", "institute"),
    ("law", "Юридический факультет", "faculty"),
    ("hist", "Исторический факультет", "faculty"),
    ("phil", "Филологический факультет", "faculty"),
    ("ir", "Факультет международных отношений", "faculty"),
    ("math", "Механико-математический факультет", "faculty"),
    ("arch", "Архитектурно-строительный факультет", "faculty"),
    ("trans", "Транспортно-энергетический факультет", "faculty"),
]


def synthetic_stats(scale: float) -> dict:
    s = lambda a, b: int(RNG.randint(a, b) * scale)  # noqa: E731
    stats = {
        "scopus": s(4, 18), "wos": s(0, 4), "koksnvo": s(15, 42), "foreign_other": s(0, 4),
        "conference": s(8, 30), "monograph": s(1, 7), "learner_pubs": s(30, 90), "prizes": s(5, 25),
        "awards": s(0, 4), "staff": max(8, s(14, 30)),
    }
    stats["prev_scopus"] = max(0, stats["scopus"] - RNG.randint(-3, 5))
    stats["prev_koksnvo"] = max(0, stats["koksnvo"] - RNG.randint(-5, 8))
    return stats


def excel_date(value: str) -> str:
    if re.fullmatch(r"4\d{4}", value or ""):
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(value))).strftime("%d.%m.%Y")
    return value


class People:
    def __init__(self):
        self.people: list[dict] = []

    def new(self, parsed: dict) -> dict:
        p = {"id": f"p{len(self.people) + 1:03d}", "surname": parsed["surname"], "initials": parsed.get("initials", ""),
             "raws": {parsed.get("raw", parsed["surname"])}, "sheets": {}, "as_supervisor": 0, "pps_rows": 0, "roster": False, "degree": "", "full_name": ""}
        self.people.append(p)
        return p

    def find(self, parsed: dict) -> dict:
        variants = [parsed]
        if parsed.get("full") and parsed.get("other"):
            variants.append({"surname": parsed["other"], "initials": parsed["surname"][0]})
        for candidate in variants:
            for p in self.people:
                if same_person(candidate, p):
                    if parsed.get("initials") and candidate is parsed and len(parsed["initials"]) > len(p.get("initials", "")):
                        p["initials"] = parsed["initials"]
                    p["raws"].add(parsed.get("raw", parsed["surname"]))
                    return p
        return self.new(parsed)


def initials_text(initials: str) -> str:
    return "".join(f"{ch}." for ch in initials)


def is_latin(text: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z .'\-]+", text or ""))


def canonical(p: dict) -> None:
    """Экранға шығатын ат. Портфолиодағы не жарияланымдағы жазылым өзгертілмейді."""
    raws = sorted(p["raws"], key=len, reverse=True)
    cyr = [r for r in raws if not is_latin(r)]
    lat = [r for r in raws if is_latin(r)]
    if not is_latin(p["surname"]) and p.get("initials"):
        p["display_name"] = f"{p['surname']} {initials_text(p['initials'])}"
    elif cyr and parse_people(cyr[0]) and parse_people(cyr[0])[0].get("initials"):
        first = parse_people(cyr[0])[0]
        p["display_name"] = f"{first['surname']} {initials_text(first['initials'])}"
    else:
        p["display_name"] = (cyr or lat or [p["surname"]])[0]
    p["display_latin"] = lat[0] if lat else f"{translit(p['surname']).title()} {initials_text(''.join(translit(c).upper()[:1] for c in p.get('initials', '')))}".strip()
    p["aliases"] = sorted({p["display_name"], p["display_latin"], *p["raws"]})


def owner_works(owner_id: str) -> list[dict]:
    """Демо иесінің Smart.ENU «Ғылыми жұмыстар» бетіндегі нақты жазбалары: есепке әлі кірмеген. Бетте көрінбеген өрістер ойдан толтырылмайды."""
    works = [
        ("Цифрлық дәуірдегі дамудың жаңа стратегиялары: BPMN арқылы цифрлық трансформация және бизнес-процестерді реинжинирингтеу", 2025),
        ("Applications in Public Sector Process Reengineering for Innovation and Efficiency", 2025),
        ("ҚР электрондық үкімет порталы үшін бизнес-процестерді модельдеу мен реинжинирингтің рөл", 2024),
        ("ҚР электрондық үкімет порталы үшін бизнес-процестерді модельдеу мен реинжинирингтің рөлі", 2024),
    ]
    return [{"id": f"w{i:03d}", "type": "conference", "role": "doctoral", "attrs": {}, "fields": {"title": title, "year": str(year)}, "matrix": {},
             "author_ids": [owner_id], "supervisor_ids": [], "reported_section": "5.4", "in_press": False, "year": year, "unit": "mgmt", "source": "smartenu",
             "work_type": "conference", "status": "создано", "confirmed": True, "created_by": owner_id, "route": [],
             "history": [{"at": "2025-12-01T09:00:00Z", "by": "Smart.ENU", "action": "Запись из «Научных работ»", "note": ""}], "_age_days": 5}
            for i, (title, year) in enumerate(works, 1)]


def workflow_examples(owner_id: str, supervisor_id: str) -> list[dict]:
    """Келісу бағытын көрсететін ойдан жасалған жазбалар. Тек демо иесіне тіркеледі және есепке кірмейді."""
    def route_of(sup_state: str, head_state: str) -> list[dict]:
        return [{"step": "supervisor", "label": "Научный руководитель", "person": supervisor_id, "state": sup_state},
                {"step": "head", "label": "Заведующий кафедрой", "role": "head", "unit": "mgmt", "state": head_state}]

    def make(i: int, title: str, index: str, source: str, issn: str, pages: str, status: str, route_steps: list[dict], age: int, note: str = "") -> dict:
        history = [{"at": "2026-01-01T09:00:00Z", "by": "Докторант PhD · Менеджмент", "action": "Запись создана", "note": ""}]
        if route_steps:
            history.append({"at": "2026-01-01T09:00:00Z", "by": "Докторант PhD · Менеджмент", "action": "Отправлено на согласование", "note": ""})
        if note:
            history.append({"at": "2026-01-01T09:00:00Z", "by": "Научный руководитель", "action": "Возвращено на доработку", "note": note})
        doc = {"id": f"e{i:03d}", "type": "article", "role": "doctoral", "attrs": {"index": index},
               "fields": {"title": f"[Пример] {title}", "source": source, "year": "2025", "issue": "2", "pages": pages, "issn": issn},
               "matrix": {}, "author_ids": [owner_id], "supervisor_ids": [], "reported_section": route("article", "doctoral", {"index": index}),
               "in_press": False, "year": 2025, "unit": "mgmt", "source": "form", "status": status, "confirmed": True, "created_by": owner_id,
               "route": route_steps, "history": history, "_age_days": age}
        if note:
            doc["return_note"] = note
        return doc

    journal = "Вестник экономики и управления (пример)"
    foreign = "Journal of Example Higher Education"
    return [
        make(1, "Цифровые сервисы в управлении вузом", "koksnvo", journal, "2345-6787", "21-30", "создано", [], 0),
        make(2, "Оценка процессов в научной отчётности", "scopus", foreign, "4567-8901", "11-24", "на доработке", route_of("returned", "wait"), 1, "[Пример] Уточните страницы и приложите скриншот из Scopus."),
        make(3, "Реинжиниринг услуг университета", "koksnvo", journal, "2345-6787", "40-52", "на согласовании", route_of("current", "wait"), 2),
        make(4, "Управление данными в высшей школе", "koksnvo", journal, "2345-6787", "53-61", "на согласовании", route_of("done", "current"), 1),
        make(5, "Process analytics in public universities", "scopus", foreign, "4567-8901", "77-90", "на согласовании", route_of("done", "current"), 4),
    ]


def main(path: str) -> None:
    public = json.loads((ROOT / "data" / "staff_public.json").read_text(encoding="utf-8"))
    parsed = read_blocks(path)
    book = People()
    rows_out = []
    for block in parsed["blocks"]:
        bid = block["id"]
        rec_type, role, attrs = attrs_from_block(bid)
        cols = {c["col"]: c["key"] for c in block["header"]}
        labels = {c["col"]: c["label"] for c in (block.get("sub_header") or block["header"])}
        for row in block["rows"]:
            fields, matrix = {}, {}
            for col, value in row.items():
                if col == "row":
                    continue
                key = cols.get(col)
                if key in ("faculty", "phone", "email"):
                    continue
                if key == "department":
                    fields["_reported_department"] = value
                    continue
                if key is None and rec_type in ("award", "scholarship"):
                    matrix[labels.get(col, col)] = value
                    continue
                if key:
                    fields[key] = value
            raw_authors = fields.pop("authors", "")
            author_text, sup_text = split_authors_supervisor(raw_authors)
            item = {"block": bid, "type": rec_type, "role": role, "attrs": attrs, "fields": fields, "matrix": matrix, "row": row["row"],
                    "sheet": block["sheet"], "raw_authors": raw_authors,
                    "had_phone": any(cols.get(c) == "phone" for c in row), "had_email": any(cols.get(c) == "email" for c in row)}
            supervisors = [book.find(x) for x in parse_people(sup_text)]
            for s in supervisors:
                s["as_supervisor"] += 1
            item["supervisors"] = supervisors
            authors = [book.find(x) for x in parse_people(author_text)]
            item["authors"] = authors
            for a in authors:
                if bid[0] == "2":
                    a["pps_rows"] += 1
                elif bid[0] in "345":
                    a["sheets"][bid[0]] = a["sheets"].get(bid[0], 0) + 1
                    if fields.get("group"):
                        a["group"] = fields["group"]
            rows_out.append(item)

    for name, degree in public["staff"]:
        parsed_name = parse_people(name)[0]
        p = book.find(parsed_name)
        p["roster"] = True
        p["degree"] = degree
        p["full_name"] = name
        if not is_latin(name):
            p["surname"], p["initials"] = parsed_name["surname"], parsed_name.get("initials", "") or p.get("initials", "")
    head_public = book.find(parse_people(public["head"]["name"])[0])
    head_public.update({"roster": True, "degree": public["head"]["degree"], "full_name": public["head"]["name"], "position_public": public["head"]["position"]})
    head_parsed = parse_people(public["head"]["name"])[0]
    head_public["surname"], head_public["initials"] = head_parsed["surname"], head_parsed.get("initials", "")

    owner = next((p for p in book.people if p["surname"] == OWNER_SURNAME), None)
    if owner is None:
        owner = book.new({"surname": OWNER_SURNAME, "initials": "Е", "raw": "Муратбеков Е."})
    owner["initials"] = "ЕД"
    owner["raws"].add("Muratbekov Y.")

    def person_role(p: dict) -> str:
        if p is owner:
            return "doctoral"
        if p["roster"] or p["as_supervisor"] > 0:
            return "teacher"
        if "5" in p["sheets"]:
            return "doctoral"
        if "4" in p["sheets"]:
            return "master"
        if "3" in p["sheets"]:
            return "student"
        return "external"

    for p in book.people:
        p["role"] = person_role(p)
        canonical(p)

    records = []
    for i, r in enumerate(rows_out, 1):
        f = {k: (excel_date(v) if k == "date" else v) for k, v in r["fields"].items()}
        matrix = dict(r["matrix"])
        if r["type"] == "award":
            f["award_name"] = f.get("award_name") or f.get("ministry") or next(iter(r["matrix"]), "") or "Награда"
            if r["block"] == "1.7":
                f["award_name"] = "Грамота министерства"
                f["org"] = r["fields"].get("ministry", "")
        author_ids = [a["id"] for a in r["authors"]]
        f["authors_text"] = r["raw_authors"]
        # Рөлдік қолжетімділікті көрсету үшін сынақ мәні: 000 коды мен example.edu ешкімге жетпейді.
        if r["type"] == "prize" and owner["id"] not in author_ids:
            if r["had_phone"]:
                f["phone"] = f"+7 000 000 {i:04d}"
            if r["had_email"]:
                f["email"] = f"demo.user{i:03d}@example.edu"
        in_press = bool(re.search(r"в\s*печати|басылымда", " ".join([f.get("pages", ""), f.get("issue", "")]), re.I))
        year = 2025
        y = re.fullmatch(r"\d{4}", f.get("year", "") or "")
        if y:
            year = int(y.group(0))
        records.append({
            "id": f"r{i:03d}", "type": r["type"], "role": r["role"], "attrs": dict(r["attrs"]), "fields": f, "matrix": matrix,
            "author_ids": author_ids, "supervisor_ids": [s["id"] for s in r["supervisors"]], "reported_section": r["block"],
            "source_ref": {"sheet": r["sheet"], "row": r["row"]}, "in_press": in_press, "year": year,
            "unit": "mgmt", "source": "report", "status": "согласовано", "confirmed": True, "route": [],
            "history": [{"at": "2025-12-01T09:00:00Z", "by": "Отчёт кафедры за 2025 год", "action": "Запись из итогового отчёта", "note": ""}],
        })

    # Растау мәртебесін тек демо иесінің жазбаларында көрсетеміз: басқа адам туралы жалған мәртебе болмайды.
    own_records = [r for r in records if owner["id"] in r["author_ids"] and r["type"] != "prize"]
    for r in own_records[:2]:
        r["confirmed"] = False
        r["pending_for"] = [owner["id"]]

    analysis = {}
    for a in parsed["analysis"]:
        if "A" in a and ("B" in a or "C" in a) and not re.match(r"Ответственный|Заведующий|Ф ЕНУ", a["A"]):
            analysis[str(a["row"])] = {"prev": a.get("B", ""), "reported": a.get("C", "")}

    head_name, resp_name = "", ""
    for a in parsed["analysis"]:
        if a.get("A", "").startswith("Ответственный"):
            resp_name = a.get("C", "")
        if a.get("A", "").startswith("Заведующий"):
            head_name = a.get("C", "")
    resp = book.find(parse_people(resp_name)[0]) if resp_name else head_public
    head = head_public
    if "display_name" not in resp:
        resp["role"] = "teacher"
        canonical(resp)

    persons = []
    for p in book.people:
        canonical(p)
        degree, position = p.get("degree", ""), p.get("position_public", "")
        persons.append({
            "id": p["id"], "display_name": p["display_name"], "display_latin": p["display_latin"], "full_name": p.get("full_name", ""),
            "role": p["role"], "unit": "mgmt" if p["role"] != "external" else None, "aliases": p["aliases"],
            "group": OWNER_GROUP if p is owner else (p.get("group", "") if p["role"] in ("student", "master", "doctoral") else ""),
            "degree": degree, "position": position, "orcid": "", "phone": "", "email": "", "on_portal": p["roster"],
        })
    persons.append(SAMPLE_STUDENT)
    director = public["school"]["director"]
    d_parsed = parse_people(director["name"])[0]
    persons += [
        {"id": "dir", "display_name": f"{d_parsed['surname']} {initials_text(d_parsed['initials'])}", "display_latin": "", "full_name": director["name"], "role": "manager", "unit": "vshet",
         "aliases": [], "group": "", "degree": "", "position": director["title"], "orcid": "", "phone": "", "email": "", "on_portal": True},
        {"id": "sci", "display_name": "Департамент науки", "display_latin": "", "full_name": "", "role": "manager", "unit": "uni",
         "aliases": [], "group": "", "degree": "", "position": "Департамент науки", "orcid": "", "phone": "", "email": "", "on_portal": False},
    ]

    supervisions, seen = [], set()
    for r, rec in zip(rows_out, records):
        for s in r["supervisors"]:
            for aid in rec["author_ids"]:
                person = next((x for x in persons if x["id"] == aid), None)
                if not person or aid == s["id"] or person["role"] not in ("student", "master", "doctoral"):
                    continue
                key = (aid, s["id"])
                if key not in seen:
                    seen.add(key)
                    supervisions.append({"learner_id": aid, "supervisor_id": s["id"], "kind": "main", "year": 2025})

    def top_learner(role: str) -> dict:
        rows = [p for p in book.people if p["role"] == role and p is not owner]
        return max(rows, key=lambda p: sum(p["sheets"].values()))

    def top_supervisor() -> dict:
        counts: dict[str, int] = {}
        for s in supervisions:
            counts[s["supervisor_id"]] = counts.get(s["supervisor_id"], 0) + 1
        best = sorted(counts.items(), key=lambda x: -x[1])
        ids = {head["id"], resp["id"]}
        pick = next(pid for pid, _ in best if pid not in ids)
        return next(p for p in book.people if p["id"] == pick)

    master, student, teacher = top_learner("master"), top_learner("student"), top_supervisor()
    positions = [
        {"id": "doctoral", "label": "Докторант PhD · Менеджмент", "role": "author", "person": owner["id"], "unit": "mgmt", "show_name": True},
        {"id": "master", "label": "Магистрант · Менеджмент", "role": "author", "person": master["id"], "unit": "mgmt"},
        {"id": "student", "label": "Студент · Менеджмент", "role": "author", "person": student["id"], "unit": "mgmt"},
        {"id": "teacher", "label": "Преподаватель, научный руководитель · Менеджмент", "role": "supervisor", "person": teacher["id"], "unit": "mgmt"},
        {"id": "resp", "label": "Ответственный по научной работе · Менеджмент", "role": "responsible", "person": resp["id"], "unit": "mgmt"},
        {"id": "head", "label": "Заведующий кафедрой · Менеджмент", "role": "head", "person": head["id"], "unit": "mgmt"},
        {"id": "director", "label": "Директор · Высшая школа экономики и туризма", "role": "director", "person": "dir", "unit": "vshet"},
        {"id": "science", "label": "Департамент науки", "role": "science", "person": "sci", "unit": "uni"},
    ]

    records += workflow_examples(owner["id"], teacher["id"])
    records += owner_works(owner["id"])

    units = list(UNITS)
    unit_stats = {}
    for u in units:
        if u.get("synthetic"):
            unit_stats[u["id"]] = synthetic_stats(1.0)
    for uid, name, kind in TOP_UNITS:
        units.append({"id": uid, "name": name, "kind": kind, "parent": "uni", "synthetic": True})
        unit_stats[uid] = synthetic_stats(RNG.choice([2.0, 3.0, 4.0]))

    schema = schema_only(parsed)

    seed = {
        "units": units, "unit_stats": unit_stats, "persons": persons, "supervisions": supervisions,
        "records": records, "positions": positions, "analysis_columns": analysis,
        "shared_between_departments": {"vshet": 3},
        "school_facts": public["school"]["facts"],
        "signers": {"responsible": resp_name, "head": head_name, "director": ""},
        "plan": {"scopus": 15, "wos": 2, "koksnvo": 30, "monograph": 6, "learner_pubs": 80, "prizes": 25},
        "manual_indicators": {"degree_share": 0.823, "foreign_scholar_share": 0.13, "funding": 55509.47, "funding_note": "39462,957 постдок", "staff_count": 23},
        "journal_watchlist": [
            {"issn": "1111-1117", "name": "International Journal of Example Studies", "reason": "Исключён из Scopus (пример)"},
            {"issn": "2222-2224", "name": "Global Review of Everything", "reason": "В списке сомнительных журналов (пример)"},
        ],
        "doctoral_requirements": {"note": "Примерные значения. Реальные требования вводит Департамент науки.",
                                  "scopus_or_wos": 1, "koksnvo": 3, "conference": 3},
        "candidates": [
            {"person": owner["id"], "title": "[Пример] Applying process mining to public service delivery in Central Asia", "journal": "Journal of Example Public Administration",
             "year": 2025, "doi": "10.5555/demo.2026.001", "issn": "1234-5679", "pages": "11-24", "source": "Crossref (пример)", "index": "scopus"},
            {"person": owner["id"], "title": "[Пример] Бизнес-процессы в цифровом государственном управлении", "journal": "Вестник экономики и управления (пример)",
             "year": 2025, "doi": "10.5555/demo.2026.002", "issn": "2345-6787", "pages": "45-53", "source": "OpenAlex (пример)", "index": "koksnvo"},
        ],
        "mock_import": {
            "platonus": [
                {"type": "article", "attrs": {"index": "koksnvo"}, "person": owner["id"], "fields": {
                    "title": "[Пример] Цифровые инструменты оценки качества государственных услуг", "source": "Вестник экономики и управления (пример)", "year": "2025", "issue": "1", "pages": "12-20", "issn": "2345-6787"}},
            ],
            "scopus": [
                {"type": "article", "attrs": {"index": "scopus"}, "person": owner["id"], "fields": {
                    "title": "[Пример] Digital maturity of Kazakhstani universities: an empirical assessment", "source": "Journal of Example Higher Education", "year": "2025", "issue": "2", "pages": "77-90", "issn": "4567-8901", "doi": "10.5555/demo.2026.010", "quartile": "Q2"}},
            ],
        },
    }
    seed = anonymize(seed)
    (ROOT / "data" / "seed.json").write_text(json.dumps(seed, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / "data" / "form_schema.json").write_text(json.dumps(schema, ensure_ascii=False, indent=1), encoding="utf-8")

    roles: dict[str, int] = {}
    for p in persons:
        roles[p["role"]] = roles.get(p["role"], 0) + 1
    print("blocks:", len(parsed["blocks"]), "records:", len(records), "persons:", len(persons), roles,
          "supervisions:", len(supervisions), "teachers with records:",
          sum(1 for p in book.people if p["role"] == "teacher" and (p["pps_rows"] or p["as_supervisor"])))


if __name__ == "__main__":
    main(sys.argv[1])

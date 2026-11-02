"""Бұрынғы Excel есепті аудиттеу және базаға көшіру. Нәтижеде адам аты емес, бөлім мен жол нөмірі көрсетіледі."""
from __future__ import annotations

import re
from pathlib import Path

from . import services, store, validators
from .catalog import attrs_from_block
from .form_parser import read_blocks
from .names import norm_title, parse_people, split_authors_supervisor

ISSUE_LABELS = {
    "ISSN_MISSING": "ISSN не указан", "ISSN_NOT_ID": "В поле ISSN другой текст", "ISSN_CHECKSUM": "Неверная контрольная цифра ISSN",
    "ISBN_MISSING": "ISBN не указан", "ISBN_NOT_ID": "В поле ISBN другой текст", "ISBN_CHECKSUM": "Неверная контрольная цифра ISBN",
    "ISSN_IN_ISBN": "На месте ISBN стоит ISSN", "PAGES_MISSING": "Нет страниц", "PLACE_MISMATCH": "Место проведения не соответствует разделу",
    "JOURNAL_IN_CONFERENCE": "Журнал в разделе конференций", "PORTAL_IN_CONFERENCE": "Портал в разделе конференций",
    "PRIZE_PLACE_MISSING": "Не указано призовое место", "PRIZE_CONFLICT": "Место и степень диплома не совпадают", "LINK_MISSING": "Нет сайта организатора",
    "IN_PRESS": "В печати", "ISSUE_DATE": "На месте номера журнала стоит дата", "DEPARTMENT_TYPO": "Ошибка в названии кафедры",
    "ISBN_SHARED": "Один ISBN в двух сборниках", "PAGE_OVERLAP": "Страницы пересекаются", "QUARTILE_MISSING": "Нет квартиля",
    "SHEETS_MISSING": "Нет печатных листов", "JOURNAL_RISK": "Риск журнала",
}


def _rows_from_parsed(parsed: dict) -> list[dict]:
    rows = []
    for block in parsed["blocks"]:
        rec_type, role, attrs = attrs_from_block(block["id"])
        cols = {c["col"]: c["key"] for c in block["header"]}
        for row in block["rows"]:
            fields = {}
            for col, value in row.items():
                key = cols.get(col)
                if col == "row" or not key or key == "faculty":
                    continue
                if key == "department":
                    fields["_reported_department"] = value
                else:
                    fields[key] = value
            raw_authors = fields.pop("authors", "")
            authors, _ = split_authors_supervisor(raw_authors)
            in_press = bool(re.search(r"в\s*печати|басылымда", f"{fields.get('pages', '')} {fields.get('issue', '')}", re.I))
            rows.append({"id": f"{block['sheet']}-{row['row']}", "type": rec_type, "roles": [role], "attrs": dict(attrs), "fields": fields,
                         "sections": [block["id"]], "section": block["id"], "in_press": in_press, "author_ids": [authors], "raw_authors": raw_authors,
                         "_ref": {"sheet": block["sheet"], "row": row["row"], "section": block["id"]}})
    return rows


def run_audit(path: str | Path) -> dict:
    parsed = read_blocks(path)
    rows = _rows_from_parsed(parsed)
    if not rows and not parsed["blocks"]:
        return {"error": "В файле не найдены разделы формы Ф ЕНУ 605-02-25"}
    watch = services.settings().get("journal_watchlist")
    coll = validators.check_collection(rows)
    findings = []
    counts: dict[str, dict] = {}
    for r in rows:
        for iss in validators.check_record(r, watch) + coll.get(r["id"], []):
            if iss["code"] == "DEPARTMENT_TYPO" and not iss["text"]:
                continue
            bucket = counts.setdefault(iss["code"], {"code": iss["code"], "label": ISSUE_LABELS.get(iss["code"], iss["code"]), "level": iss["level"], "count": 0})
            bucket["count"] += 1
            findings.append({"section": r["section"], "sheet": r["_ref"]["sheet"], "row": r["_ref"]["row"], "code": iss["code"], "level": iss["level"], "text": iss["text"]})
    dups = validators.find_duplicates(rows)
    dup_out = []
    extra = 0
    pps_extra = 0
    by_id = {r["id"]: r for r in rows}
    for d in dups:
        if d["kind"] == "similar":
            continue
        refs = [by_id[i]["_ref"] for i in d["record_ids"]]
        dup_out.append({"kind": d["kind"], "text": d["text"], "rows": refs})
        extra += len(refs) - 1
        pps_refs = [x for x in refs if x["section"][0] == "2"]
        pps_extra += max(0, len(pps_refs) - 1)
    pubs = [r for r in rows if r["type"] in ("article", "conference", "monograph")]
    pps = [r for r in pubs if r["section"][0] == "2"]
    learners = {k: [r for r in pubs if r["section"][0] == k] for k in "345"}
    analysis = {str(a["row"]): a for a in parsed["analysis"]}
    compare = []
    def add(label: str, row: int, actual: int):
        reported = analysis.get(str(row), {}).get("C")
        try:
            reported_num = float(reported)
        except (TypeError, ValueError):
            reported_num = None
        compare.append({"label": label, "reported": reported, "actual": actual, "match": reported_num == actual})
    add("Публикации ППС", 5, len(pps) - pps_extra)
    add("Журналы КОКСНВО", 14, len({norm_title(r["fields"].get("title", "")) for r in pps if r["section"] == "2.4б"}))
    add("Scopus", 13, sum(1 for r in pps if r["section"] == "2.3"))
    add("Публикации студентов", 24, len(learners["3"]))
    add("Публикации магистрантов", 25, len(learners["4"]))
    add("Публикации докторантов", 26, len(learners["5"]))
    return {
        "blocks": len(parsed["blocks"]), "rows": len(rows), "publications": len(pubs),
        "counts": sorted(counts.values(), key=lambda c: ({"error": 0, "warn": 1, "info": 2}[c["level"]], -c["count"])),
        "findings": findings[:400], "duplicates": dup_out, "duplicate_rows": extra, "pps_duplicate_rows": pps_extra,
        "compare": compare, "formulas_note": "Итоговая страница сверена со значениями в файле",
        "errors": sum(1 for f in findings if f["level"] == "error"), "warnings": sum(1 for f in findings if f["level"] == "warn"),
    }


def import_rows(path: str | Path, position: dict) -> dict:
    """Базада жоқ жолдарды ғана көшіреді. Байланыс мәліметі алынбайды, ал жолдар есепке меңгеруші келіскен соң кіреді."""
    parsed = read_blocks(path)
    rows = _rows_from_parsed(parsed)
    existing = {norm_title(services.display_title(r)) for r in store.records(include_merged=True)}
    added, skipped = 0, 0
    for r in rows:
        title = norm_title(services.display_title(r))
        if not title or title in existing:
            skipped += 1
            continue
        existing.add(title)
        fields = {k: v for k, v in r["fields"].items() if k not in ("phone", "email")}
        fields["authors_text"] = r["raw_authors"]
        year = 2025
        m = re.search(r"20\d{2}", fields.get("year", "") or "")
        if m:
            year = int(m.group(0))
        names = [p.get("raw") or p["surname"] for p in parse_people(r["author_ids"][0])]
        resolved = services.resolve_authors(names)
        doc = {"id": store.new_record_id(), "type": r["type"], "roles": r["roles"], "attrs": r["attrs"], "fields": fields, "matrix": {},
               "author_ids": [m["person_id"] for m in resolved["matched"]], "external_authors": resolved["external"], "supervisor_ids": [], "reported_section": r["section"],
               "sections": r["sections"], "in_press": r["in_press"], "year": year, "unit": "mgmt", "source": "import", "status": "на согласовании",
               "confirmed": True, "evidence": [], "created_at": store.now(), "stage_since": store.now(), "created_by": position.get("person"),
               "route": [{"step": "head", "label": services.STEP_LABELS["head"], "role": "head", "unit": "mgmt", "state": "current"}],
               "history": [{"at": store.now(), "by": position.get("label"), "action": "Импорт из прошлого отчёта", "note": ""}]}
        store.save_record(doc)
        added += 1
    if added:
        store.notify(f"На согласование: строки из загруженного отчёта, записей {added}", role="head", unit="mgmt", link="approvals")
    store.log(position, "Импорт из отчёта", "", f"на согласовании {added}, пропущено как уже существующих {skipped}")
    return {"added": added, "skipped": skipped}

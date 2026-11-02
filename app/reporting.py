"""Есептерді шығару: Ф ЕНУ 605-02-25, тұлға тізімі, кафедра бөлімі, жиынтық кесте, дәлел пакеті."""
from __future__ import annotations

import csv
import io
import json
import math
import re
import zipfile
from collections import defaultdict
from copy import copy
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import column_index_from_string, get_column_letter

from . import analytics, services, store
from .catalog import INDEX_LABELS, TYPES, display_title

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "data" / "f605_template.xlsx"
LAYOUT = ROOT / "data" / "f605_layout.json"
THIN = Side(style="thin", color="94A3B8")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEAD_FILL = PatternFill("solid", fgColor="E8EEF7")
LINE_HEIGHT = 15.75
SHEET_NAMES = ["Титульный", "Научный потенциал", "НИР студентов", "Осн. итоги науч. деят-ти ППС",
               "НИР магистрантов", "НИР докторантов", "Анализ НИР факультета"]

EVIDENCE_RULES = {
    "скриншот": ("2.2", "2.3", "3.1", "3.2", "4.1", "4.2", "5.1", "5.2"),
    "подтверждающий документ": ("3.6", "3.7", "3.8", "4.6", "4.7", "4.8", "5.6", "5.7", "5.8"),
    "титульный лист": ("2.7", "2.8", "2.9", "2.10", "2.11", "2.12"),
}


def form_schema() -> dict:
    return json.loads((ROOT / "data" / "form_schema.json").read_text(encoding="utf-8"))


def evidence_need(section: str) -> str | None:
    for label, sections in EVIDENCE_RULES.items():
        if section in sections:
            return label
    return None


def _person_names(rec: dict, persons: dict, latin: bool) -> str:
    # Есептегі жазылым сол күйінде қалады. Мысалы, авторлар реті мен ғылыми жетекші мәтіні өзгермейді.
    printed = rec.get("fields", {}).get("authors_text")
    if printed:
        return printed
    names = []
    for pid in rec.get("author_ids", []):
        p = persons.get(pid)
        if p:
            names.append(p["display_latin"] if latin else p["display_name"])
    names += rec.get("external_authors", [])
    text = ", ".join(names)
    bosses = [persons[s]["display_name"] for s in rec.get("supervisor_ids", []) if s in persons and s not in rec.get("author_ids", [])]
    if bosses and not latin:
        text = f"{text}. Научный руководитель: {', '.join(bosses)}"
    elif bosses:
        text = f"{text}. Scientific advisor: {', '.join(persons[s]['display_latin'] for s in rec.get('supervisor_ids', []) if s in persons and s not in rec.get('author_ids', []))}"
    return text


def _cell_value(key: str, label: str, rec: dict, persons: dict, ctx: dict) -> str:
    f = rec.get("fields", {})
    first = persons.get(rec["author_ids"][0], {}) if rec.get("author_ids") else {}
    if key == "faculty":
        return ctx["faculty_short"]
    if key == "department":
        return ctx["department"]
    if key == "authors":
        return _person_names(rec, persons, "английском" in label.lower())
    if key in ("phone", "email"):
        return f.get(key, "") if ctx["pii"] else ("•••" if f.get(key) else "")
    if key == "group":
        return f.get("group") or first.get("group", "")
    if key == "degree":
        return f.get("degree") or first.get("degree", "")
    if key == "position":
        return f.get("position") or first.get("position", "")
    if key == "source":
        return f.get("source", "")
    if key == "impact":
        return f.get("impact") or (f"https://doi.org/{f['doi']}" if f.get("doi") else "")
    if key == "date":
        return f.get("date", "")
    if key:
        return f.get(key, "")
    return ""


def _copy_sheet_setup(src, dst) -> None:
    for key, dim in src.column_dimensions.items():
        dst.column_dimensions[key] = copy(dim)
        dst.column_dimensions[key].worksheet = dst
    dst.sheet_format = copy(src.sheet_format)
    dst.sheet_properties = copy(src.sheet_properties)
    dst.page_margins = copy(src.page_margins)
    dst.page_setup = copy(src.page_setup)
    dst.page_setup.worksheet = dst
    dst.print_options = copy(src.print_options)


def _copy_row(src, dst, src_row: int, dst_row: int, columns: int) -> None:
    for col in range(1, columns + 1):
        s = src.cell(src_row, col)
        d = dst.cell(dst_row, col)
        if s.has_style:
            d._style = copy(s._style)
        if s.value is not None:
            d.value = s.value
    height = src.row_dimensions[src_row].height
    if height:
        dst.row_dimensions[dst_row].height = height


def _column_width(ws, col: int) -> float:
    for dim in ws.column_dimensions.values():
        low = dim.min or column_index_from_string(dim.index)
        high = dim.max or low
        if low <= col <= high and dim.width:
            return dim.width
    return 9.1


def _row_height(ws, row: int, columns: int) -> float:
    """Excel ашқанда мәтін кесілмеуі үшін жолдың биіктігін мәтін ұзындығынан есептейді."""
    lines = 1
    for col in range(1, columns + 1):
        value = ws.cell(row, col).value
        if value in (None, ""):
            continue
        width = max(_column_width(ws, col) * 0.95, 4)
        need = sum(max(1, math.ceil(len(part) / width)) for part in str(value).split("\n"))
        lines = max(lines, need)
    return min(409, max(LINE_HEIGHT, lines * LINE_HEIGHT))


def _write_data_row(ws, row: int, item: dict, rec: dict, persons: dict, ctx: dict) -> None:
    header = item["header"]
    sub = item.get("sub_header")
    none_cols = [h for h in header if h.get("key") is None]
    for h in header:
        if h.get("key"):
            ws[f"{h['col']}{row}"].value = _cell_value(h["key"], h["label"], rec, persons, ctx)
    matrix = rec.get("matrix") or {}
    placed = False
    for h in (sub or []) + none_cols:
        if h["label"] in matrix:
            ws[f"{h['col']}{row}"].value = matrix[h["label"]]
            placed = True
    if not placed and rec["type"] in ("award", "scholarship"):
        target = (sub or none_cols or [None])[0]
        if target and rec["fields"].get("award_name"):
            ws[f"{target['col']}{row}"].value = rec["fields"]["award_name"]


def _last_column(item: dict) -> int:
    cols = [column_index_from_string(h["col"]) for h in item["header"]]
    cols += [column_index_from_string(h["col"]) for h in item.get("sub_header") or []]
    return max(cols)


def _rebuild_sheet(wb, src, items: list[dict], blocks: list[dict], footer_row: int | None, rows_by_section: dict, persons: dict, ctx: dict):
    """Парақты нысаннан қайта жинайды: тақырып пен пішім сол күйінде, дерек жолдары жазба санына қарай."""
    dst = wb.create_sheet(src.title + "~")
    _copy_sheet_setup(src, dst)
    by_id = {i["id"]: i for i in items if not i.get("footer")}
    columns = src.max_column
    row_map: dict[int, int] = {}
    out = 1

    def copy_range(first: int, last: int) -> None:
        nonlocal out
        for r in range(first, last + 1):
            _copy_row(src, dst, r, out, columns)
            row_map[r] = out
            out += 1

    if blocks and blocks[0]["title_row"] > 1:
        copy_range(1, blocks[0]["title_row"] - 1)
    for block in blocks:
        item = by_id[block["id"]]
        copy_range(block["title_row"], block["head_last"])
        if not block["has_table"]:
            continue
        rows = rows_by_section.get(block["id"], [])
        last_col = _last_column(item)
        has_row = block["data_first"] < block["next_row"]
        for i, rec in enumerate(rows):
            if has_row:
                # Нысандағы әр жолдың пішімі сол жолға қайта қолданылады, артық жолдарға соңғысы.
                _copy_row(src, dst, min(block["data_first"] + i, max(block["data_last"], block["data_first"])), out, columns)
                for col in range(1, columns + 1):
                    dst.cell(out, col).value = None
            else:
                for col in range(1, last_col + 1):
                    s = src.cell(block["head_last"], col)
                    d = dst.cell(out, col)
                    d._style = copy(s._style)
                    d.font = Font(name=s.font.name, sz=s.font.sz, b=False)
            _write_data_row(dst, out, item, rec, persons, ctx)
            dst.row_dimensions[out].height = max(dst.row_dimensions[out].height or 0, _row_height(dst, out, last_col))
            out += 1
        # Бос қалған жолдар нысандағыдай сақталады.
        blank_from = block["data_last"] + 1 if block["data_count"] else block["data_first"]
        if rows and not block["data_count"]:
            blank_from = block["next_row"]
        copy_range(blank_from, block["next_row"] - 1)
    if footer_row:
        copy_range(footer_row, footer_row)
    for merged in src.merged_cells.ranges:
        if merged.min_row in row_map and merged.max_row in row_map:
            top, bottom = row_map[merged.min_row], row_map[merged.max_row]
            if bottom - top == merged.max_row - merged.min_row:
                dst.merge_cells(start_row=top, start_column=merged.min_col, end_row=bottom, end_column=merged.max_col)
    title = src.title
    wb.remove(src)
    dst.title = title
    return dst


def f605_bytes(snapshot: dict, pii: bool = False) -> bytes:
    schema = form_schema()
    layout = json.loads(LAYOUT.read_text(encoding="utf-8"))
    unit = store.units()[snapshot["unit"]]
    units = store.units()
    parent = units.get(unit.get("parent"), {})
    year = snapshot["year"]
    faculty_name = (parent.get("names_by_year") or {}).get(str(year), parent.get("name", ""))
    faculty_short = "ЭФ" if str(year) in (parent.get("names_by_year") or {}) else "ВШЭТ"
    persons = snapshot["persons"]
    rows_by_section: dict[str, list[dict]] = defaultdict(list)
    for rec in snapshot["records"]:
        for section in rec.get("sections", []):
            rows_by_section[section].append(rec)

    wb = load_workbook(TEMPLATE)
    order = list(wb.sheetnames)
    ctx = {"pii": pii, "faculty_short": faculty_short, "department": unit["name"]}
    for name in order:
        ws = wb[name]
        if name == "Титульный":
            _fill_title(ws, year, unit, faculty_name, snapshot)
        elif name == "Анализ НИР факультета":
            _fill_analysis(ws, snapshot)
        else:
            _rebuild_sheet(wb, ws, schema["sheets"][name]["items"], layout["sheets"][name], layout["footers"].get(name), rows_by_section, persons, ctx)
    wb._sheets = [wb[name] for name in order]
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _fill_title(ws, year: int, unit: dict, faculty_name: str, snapshot: dict) -> None:
    protocol = (snapshot.get("state") or {}).get("protocol") or {}
    for row in ws.iter_rows():
        for cell in row:
            if not isinstance(cell.value, str):
                continue
            text = cell.value
            text = re.sub(r"за \d{4} год", f"за {year} год", text)
            text = re.sub(r"Астана\s*[–-]\s*\d{4}", f"Астана – {year}", text)
            if "Кафедра" in text and "МЕНЕДЖМЕНТ" in text.upper():
                text = f" Кафедра {unit['name'].upper()} "
            if "факультет" in text.lower() and "Экономический" in text and str(year) != "2025":
                text = faculty_name
            if text.startswith("Протокол") and protocol.get("no"):
                text = f"Протокол № {protocol['no']}"
            if "«____»" in text and protocol.get("date") and cell.row > 20:
                text = protocol["date"]
            cell.value = text


def _indicator_value(value):
    """Нысанда мәні жоқ көрсеткіш сызықшамен жазылады."""
    if value in (None, "", 0, 0.0):
        return "-"
    if isinstance(value, float):
        if abs(value) < 1:
            return round(value, 3)
        return round(value, 1) if abs(value) < 100 else round(value, 2)
    return value


def _fill_analysis(ws, snapshot: dict) -> None:
    for ind in snapshot["indicators"]:
        row = ind["row"]
        ws[f"B{row}"] = _maybe_number(ind.get("prev"))
        # Жазбалардан есептелмейтін көрсеткіш үшін нысандағы мән қалады.
        ws[f"C{row}"] = _indicator_value(ind["value"] if ind["value"] is not None else _maybe_number(ind.get("reported")))
        if ind.get("note"):
            ws[f"D{row}"] = ind["note"]
    signers = store.kv_get("signers", {}) or {}
    for row in range(1, ws.max_row + 1):
        label = ws[f"A{row}"].value
        if isinstance(label, str) and label.startswith("Ответственный"):
            ws[f"C{row}"] = signers.get("responsible", "")
        elif isinstance(label, str) and label.startswith("Заведующий"):
            ws[f"C{row}"] = signers.get("head", "")


def _maybe_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return value or ""


def person_list_bytes(person_id: str) -> bytes:
    """«Список научных работ»: бір дерек, басқа нысан."""
    persons = store.persons()
    p = persons[person_id]
    rows = [r for r in store.records(approved_only=True) if person_id in r.get("author_ids", []) and r["type"] in ("article", "conference", "monograph")]
    rows.sort(key=lambda r: (-r["year"], display_title(r)))
    wb = Workbook()
    ws = wb.active
    ws.title = "Список научных работ"
    ws["A1"] = f"Список научных работ: {p['display_name']}"
    ws["A1"].font = Font(bold=True, size=12)
    heads = ["№", "Название публикации", "Вид", "Печатный или электронный", "Издание, №, год, страницы", "Объём, п.л.", "Соавторы"]
    widths = [5, 55, 24, 16, 50, 10, 40]
    for i, (h, w) in enumerate(zip(heads, widths), 1):
        c = ws.cell(row=3, column=i, value=h)
        c.font = Font(bold=True, size=9)
        c.fill = HEAD_FILL
        c.border = BORDER
        c.alignment = Alignment(wrap_text=True, horizontal="center")
        ws.column_dimensions[get_column_letter(i)].width = w
    for n, r in enumerate(rows, 1):
        f = r["fields"]
        place = ", ".join(x for x in (f.get("source") or f.get("publisher"), f.get("issue"), str(r["year"]), f.get("pages")) if x)
        co = [persons[a]["display_name"] for a in r["author_ids"] if a != person_id and a in persons] + r.get("external_authors", [])
        kind = TYPES[r["type"]]["label"]
        if r["type"] == "article":
            kind = INDEX_LABELS.get(r["attrs"].get("index"), kind)
        values = [n, display_title(r), kind, "Печатный", place, f.get("sheets", ""), ", ".join(co)]
        for i, v in enumerate(values, 1):
            c = ws.cell(row=3 + n, column=i, value=v)
            c.border = BORDER
            c.font = Font(size=9)
            c.alignment = Alignment(wrap_text=True, vertical="top")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def department_section_bytes(unit: str, year: int) -> bytes:
    """Кафедраның жылдық есебіне арналған ғылыми бөлім: сол дерек, қысқа кесте."""
    rows = store.records(unit=unit, year=year, approved_only=True)
    ov = analytics.overview(unit, year)
    plan = analytics.plan_fact(unit, year)
    teachers = analytics.teachers_table(unit, year)
    wb = Workbook()
    ws = wb.active
    ws.title = "Научный раздел"
    ws["A1"] = f"Кафедра {store.units()[unit]['name']}: итоги научной работы за {year} год"
    ws["A1"].font = Font(bold=True, size=12)
    ws.column_dimensions["A"].width = 44
    for col in "BCDEFGH":
        ws.column_dimensions[col].width = 13
    r = 3
    ws.cell(row=r, column=1, value="Показатель").font = Font(bold=True)
    ws.cell(row=r, column=2, value="Значение").font = Font(bold=True)
    r += 1
    for card in ov["cards"]:
        ws.cell(row=r, column=1, value=card["label"])
        ws.cell(row=r, column=2, value=card["value"])
        r += 1
    r += 1
    for i, h in enumerate(("План и факт", "План", "Факт", "%"), 1):
        ws.cell(row=r, column=i, value=h).font = Font(bold=True)
    r += 1
    for p in plan:
        for i, v in enumerate((p["label"], p["plan"], p["fact"], p["percent"]), 1):
            ws.cell(row=r, column=i, value=v)
        r += 1
    r += 1
    for i, h in enumerate(("Преподаватель", "Scopus", "WoS", "КОКСНВО", "Конф.", "Моногр.", "Подопечные", "Всего"), 1):
        ws.cell(row=r, column=i, value=h).font = Font(bold=True)
    r += 1
    for t in teachers:
        for i, v in enumerate((t["name"], t["scopus"], t["wos"], t["koksnvo"], t["conference"], t["monograph"],
                               t["students"] + t["masters"] + t["doctorals"], t["total"]), 1):
            ws.cell(row=r, column=i, value=v)
        r += 1
    ws.cell(row=r + 1, column=1, value=f"Записей: {len(rows)}").font = Font(italic=True, size=8)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def summary_bytes(parent: str, year: int) -> bytes:
    """Жоғары мектеп не университет бойынша жиынтық кесте."""
    data = analytics.compare(parent, year)
    wb = Workbook()
    ws = wb.active
    ws.title = "Сводная"
    ws["A1"] = f"{data['parent_name']}: сводка за {year} год"
    ws["A1"].font = Font(bold=True, size=12)
    heads = ["Подразделение", "Scopus", "WoS", "КОКСНВО", "Конференции", "Монографии", "Публикации обучающихся", "Призёры", "Статус", "Данные"]
    widths = [44, 9, 8, 10, 13, 12, 16, 10, 14, 14]
    for i, (h, w) in enumerate(zip(heads, widths), 1):
        c = ws.cell(row=3, column=i, value=h)
        c.font = Font(bold=True, size=9)
        c.fill = HEAD_FILL
        c.alignment = Alignment(wrap_text=True, horizontal="center")
        ws.column_dimensions[get_column_letter(i)].width = w
    r = 4
    for row in data["rows"]:
        values = [row["name"], row["scopus"], row["wos"], row["koksnvo"], row["conference"], row["monograph"], row["learner_pubs"],
                  row["prizes"], row.get("status", ""), "условные" if row["synthetic"] else "из отчёта"]
        for i, v in enumerate(values, 1):
            ws.cell(row=r, column=i, value=v).font = Font(size=9)
        r += 1
    t = data["total"]
    values = ["Всего (совместная статья считается один раз)", t["scopus"], t["wos"], t["koksnvo"], t["conference"], t["monograph"], t["learner_pubs"], t["prizes"]]
    for i, v in enumerate(values, 1):
        ws.cell(row=r, column=i, value=v).font = Font(bold=True, size=9)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def evidence_summary(rows: list[dict]) -> dict:
    need, have = 0, 0
    per_kind: dict[str, dict] = {}
    missing = []
    for r in rows:
        needs = {evidence_need(s) for s in r.get("sections", [])} - {None}
        for kind in needs:
            need += 1
            ok = bool(r.get("evidence"))
            have += ok
            bucket = per_kind.setdefault(kind, {"need": 0, "have": 0})
            bucket["need"] += 1
            bucket["have"] += ok
            if not ok:
                missing.append({"id": r["id"], "title": display_title(r), "kind": kind, "sections": r.get("sections", [])})
    return {"need": need, "have": have, "kinds": per_kind, "missing": missing}


def evidence_zip_bytes(unit: str, year: int) -> bytes:
    rows = store.records(unit=unit, year=year, approved_only=True)
    buf = io.BytesIO()
    manifest = io.StringIO()
    writer = csv.writer(manifest)
    writer.writerow(["Раздел", "Запись", "Нужен документ", "Файл", "Статус"])
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for r in rows:
            for section in r.get("sections", []):
                kind = evidence_need(section)
                files = r.get("evidence", [])
                if not kind and not files:
                    continue
                if not files:
                    writer.writerow([section, display_title(r), kind or "", "", "нет"])
                for e in files:
                    path = store.upload_path(e["stored"])
                    arc = f"{section}/{r['id']}_{Path(e['filename']).name}"
                    if path:
                        z.write(path, arc)
                    writer.writerow([section, display_title(r), kind or "", e["filename"], "есть"])
        z.writestr("manifest.csv", "﻿" + manifest.getvalue())
    return buf.getvalue()


def current_snapshot(unit: str, year: int) -> dict:
    return services.snapshot(unit, year)

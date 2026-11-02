"""Ф ЕНУ 605-02-25 нысанын оқу: бөлімдер, бағандар және жолдар."""
from __future__ import annotations

import re
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

SHEET_ORDER = [
    "Титульный",
    "Научный потенциал",
    "НИР студентов",
    "Осн. итоги науч. деят-ти ППС",
    "НИР магистрантов",
    "НИР докторантов",
    "Анализ НИР факультета",
]

TITLE_RX = re.compile(r"^\s*(\d\.\d+|\d\.\s|[абв]\))")

COLUMN_RULES: list[tuple[str, str]] = [
    (r"^факультет", "faculty"),
    (r"^кафедра", "department"),
    (r"руководител", "project_lead"),
    (r"ф\.и\.о", "authors"),
    (r"наименование публикации|название публикации", "title"),
    (r"наименование журнала|полное наименование сборника", "source"),
    (r"наименование издательства", "publisher"),
    (r"город издательства", "city"),
    (r"^год$", "year"),
    (r"номер журнала", "issue"),
    (r"^страницы", "pages"),
    (r"^issn", "issn"),
    (r"^isbn", "isbn"),
    (r"импакт", "impact"),
    (r"квартиль", "quartile"),
    (r"кол-во п\.л", "sheets"),
    (r"гриф", "grif"),
    (r"ученая степень", "degree"),
    (r"должность по проекту", "project_role"),
    (r"должность", "position"),
    (r"название журнала", "journal"),
    (r"^период", "period"),
    (r"№ группы", "group"),
    (r"дата получения награды", "award_place"),
    (r"наименование конференции", "event"),
    (r"место проведения", "venue"),
    (r"мобильного", "phone"),
    (r"e-mail", "email"),
    (r"ссылка", "link"),
    (r"^страна", "country"),
    (r"название проекта", "project"),
    (r"степень участия", "participation"),
    (r"дата присуждения|дата проведения", "date"),
    (r"название конкурса", "contest"),
    (r"^результат", "result"),
    (r"наименование организации", "org"),
    (r"наименование министерства", "ministry"),
]


def column_key(label: str) -> str | None:
    text = re.sub(r"\s+", " ", str(label or "")).strip().lower()
    for rx, key in COLUMN_RULES:
        if re.search(rx, text):
            return key
    return None


def block_id(title: str, parent: str) -> str:
    text = title.strip()
    m = re.match(r"^(\d\.\d+)", text)
    if m:
        return m.group(1)
    m = re.match(r"^([абв])\)", text)
    if m:
        return f"{parent}{m.group(1)}"
    return text.split()[0].rstrip(".")


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r"[ \t]+", " ", str(value)).strip()


def _rows(ws) -> dict[int, dict[str, str]]:
    rows: dict[int, dict[str, str]] = {}
    for row in ws.iter_rows():
        data = {}
        for cell in row:
            text = _cell_text(cell.value)
            if text:
                data[cell.column_letter] = text
        if data:
            rows[row[0].row] = data
    return rows


def read_blocks(path: str | Path) -> dict:
    """Файлдан бөлімдер мен жолдарды оқиды. Форматын емес, құрылымын қайтарады."""
    wb = load_workbook(path, data_only=True)
    result = {"sheets": {}, "blocks": [], "title_sheet": {}, "analysis": []}
    for name in wb.sheetnames:
        ws = wb[name]
        if name not in SHEET_ORDER:
            continue
        rows = _rows(ws)
        widths = {}
        for letter, dim in ws.column_dimensions.items():
            if dim.width:
                widths[letter] = round(dim.width, 1)
        heights = {}
        result["sheets"][name] = {"widths": widths, "items": []}
        items = result["sheets"][name]["items"]
        if name == "Титульный":
            result["title_sheet"] = {str(r): d for r, d in rows.items()}
            continue
        if name == "Анализ НИР факультета":
            for r in sorted(rows):
                result["analysis"].append({"row": r, **rows[r]})
            continue
        parent = ""
        current = None
        ordered = sorted(rows)
        for idx, r in enumerate(ordered):
            d = rows[r]
            first_col = next(iter(d))
            first = d[first_col]
            if TITLE_RX.match(first) and len(d) <= 2 and len(first) > 6:
                bid = block_id(first, parent)
                if re.match(r"^\d\.\d+", first):
                    parent = bid
                current = {"id": bid, "title": first, "col": first_col, "sheet": name,
                           "header": None, "sub_header": None, "rows": [], "row": r}
                items.append(current)
                continue
            if current is None:
                continue
            if current["header"] is None and (d.get("A", "").lower().startswith("факультет") or
                                              "ф.и.о" in " ".join(d.values()).lower()[:300]):
                current["header"] = [{"col": c, "label": t, "key": column_key(t)} for c, t in d.items()]
                nxt = rows.get(ordered[idx + 1]) if idx + 1 < len(ordered) else None
                if nxt and "A" not in nxt and "C" not in nxt and len(nxt) > 1:
                    current["sub_header"] = [{"col": c, "label": t} for c, t in nxt.items()]
                    current["_skip"] = ordered[idx + 1]
                result["blocks"].append(current)
                continue
            if current.get("_skip") == r:
                continue
            if current["header"] is None:
                continue
            if d.get("A", "").startswith("Ф ЕНУ"):
                items.append({"id": "footer", "title": d["A"], "col": "A", "sheet": name, "footer": True})
                continue
            if "C" in d and len(d) >= 2 and not d["C"].lower().startswith("ф.и.о"):
                current["rows"].append({"row": r, **d})
    return result


def schema_only(parsed: dict) -> dict:
    """Шаблонға тек құрылым қалады: бірде-бір дерек жолы сақталмайды."""
    sheets = {}
    for name, sheet in parsed["sheets"].items():
        items = []
        for item in sheet["items"]:
            clean = {k: v for k, v in item.items() if k not in {"rows", "_skip"}}
            items.append(clean)
        sheets[name] = {"widths": sheet["widths"], "items": items}
    title = {}
    for r, d in parsed["title_sheet"].items():
        title[r] = d
    analysis = [{"row": a["row"], "label": a.get("A", "")} for a in parsed["analysis"]]
    return {"sheets": sheets, "title_sheet": title, "analysis": analysis,
            "sheet_order": [s for s in SHEET_ORDER if s in sheets or s in ("Титульный", "Анализ НИР факультета")]}


def read_layout(path: str | Path) -> dict:
    """Әр бөлімнің нысандағы жолдары: тақырып, баған аттары, дерек және келесі бөлім басталатын жол."""
    parsed = read_blocks(path)
    wb = load_workbook(path, data_only=True)
    layout: dict = {"sheets": {}}
    for name, sheet in parsed["sheets"].items():
        if name in ("Титульный", "Анализ НИР факультета"):
            continue
        ws = wb[name]
        rows = _rows(ws)
        items = [i for i in sheet["items"] if not i.get("footer")]
        footer_row = next((r for r in sorted(rows) if rows[r].get("A", "").startswith("Ф ЕНУ")), None)
        blocks = []
        for idx, item in enumerate(items):
            next_row = items[idx + 1]["row"] if idx + 1 < len(items) else (footer_row or max(rows) + 1)
            head_last = item["row"]
            if item.get("header"):
                head_first = next(r for r in sorted(rows) if r > item["row"] and _is_header(rows[r]))
                head_last = head_first
                if item.get("sub_header"):
                    head_last += 1
                # Баған аты екі жолға біріктірілсе, екінші жол да тақырыпқа жатады.
                for merged in ws.merged_cells.ranges:
                    if merged.min_row == head_first:
                        head_last = max(head_last, merged.max_row)
            data_rows = item.get("rows") or []
            blocks.append({
                "id": item["id"], "title_row": item["row"], "head_last": head_last,
                "data_first": head_last + 1 if item.get("header") else next_row, "data_count": len(data_rows),
                "data_last": data_rows[-1]["row"] if data_rows else head_last,
                "next_row": next_row, "has_table": bool(item.get("header")),
            })
        layout["sheets"][name] = blocks
        layout.setdefault("footers", {})[name] = footer_row
    return layout


def _is_header(row: dict) -> bool:
    return row.get("A", "").lower().startswith("факультет") or "ф.и.о" in " ".join(row.values()).lower()[:300]


def letter(i: int) -> str:
    return get_column_letter(i)

"""ЖИ-сіз тексерулер: идентификатор, бет, қайталану, бөлімге сәйкестік."""
from __future__ import annotations

import re
from collections import defaultdict

from .names import norm_title

EXCEL_DATE = re.compile(r"^4\d{4}$")
FOREIGN_SIGNS = re.compile(r"boston|harvard|\busa?\b|\bсша\b|москв|екатеринбург|бишкек|рф\b|российск|montenegro|türkiye|турци", re.I)
JOURNAL_SIGNS = re.compile(r"журнал|journal|вестник|хабаршы|научный журнал|молодой ученый|endless light", re.I)
PORTAL_SIGNS = re.compile(r"портал|democracy\.kz", re.I)


def issn_ok(value: str) -> bool:
    digits = re.sub(r"[^0-9Xx]", "", value or "")
    if len(digits) != 8 or not digits[:7].isdigit():
        return False
    total = sum(int(ch) * w for ch, w in zip(digits[:7], range(8, 1, -1)))
    check = (11 - total % 11) % 11
    return ("X" if check == 10 else str(check)) == digits[7].upper()


def isbn_ok(value: str) -> bool:
    digits = re.sub(r"[^0-9Xx]", "", value or "")
    if len(digits) == 13 and digits.isdigit():
        return sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(digits)) % 10 == 0
    if len(digits) == 10:
        total = sum((10 - i) * (10 if c in "Xx" else int(c)) for i, c in enumerate(digits) if c.isdigit() or c in "Xx")
        return total % 11 == 0
    return False


def extract_issn(value: str) -> list[str]:
    return ["".join(m) for m in re.findall(r"(?<![\d\-])(\d{4})\s*[-–]?\s*(\d{3}[\dXx])(?![\d\-])", value or "")]


def extract_isbn(value: str) -> list[str]:
    return [re.sub(r"\D", "", m) for m in re.findall(r"97[89][-\s–—]?(?:\d[-\s–—]?){9}\d", value or "")]


def page_range(text: str) -> tuple[int, int] | None:
    m = re.search(r"(\d{1,5})\s*[-–—]\s*(\d{1,5})", text or "")
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return (a, b) if a <= b else None


def issue(code: str, level: str, field: str, text: str) -> dict:
    return {"code": code, "level": level, "field": field, "text": text}


def check_record(rec: dict, watchlist: list[dict] | None = None) -> list[dict]:
    """Бір жазбаны тексереді. level: error — түзету керек, warn — адам қарайды, info — ескерту."""
    out: list[dict] = []
    t, f, attrs = rec["type"], rec.get("fields", {}), rec.get("attrs", {})
    if t == "article":
        value = f.get("issn", "")
        if not value:
            out.append(issue("ISSN_MISSING", "warn", "issn", "ISSN не указан"))
        else:
            tokens = extract_issn(value)
            if not tokens:
                out.append(issue("ISSN_NOT_ID", "error", "issn", f"В этом поле нет ISSN: «{value[:40]}»"))
            elif not all(issn_ok(x) for x in tokens):
                out.append(issue("ISSN_CHECKSUM", "error", "issn", f"Неверная контрольная цифра ISSN: {value[:30]}"))
        if not f.get("pages"):
            out.append(issue("PAGES_MISSING", "warn", "pages", "Страницы не указаны"))
        if attrs.get("index") in ("wos", "scopus") and not f.get("quartile") and not f.get("impact"):
            out.append(issue("QUARTILE_MISSING", "info", "quartile", "Нет квартиля или импакт-фактора"))
    if t == "conference":
        value = f.get("isbn", "")
        if not value:
            out.append(issue("ISBN_MISSING", "warn", "isbn", "ISBN не указан"))
        else:
            tokens = extract_isbn(value)
            if not tokens:
                hint = extract_issn(value)
                if hint and any(issn_ok(x) for x in hint):
                    out.append(issue("ISSN_IN_ISBN", "warn", "isbn", "На месте ISBN стоит ISSN, возможно, это журнал"))
                else:
                    out.append(issue("ISBN_NOT_ID", "error", "isbn", f"В этом поле нет ISBN: «{value[:40]}»"))
            elif not all(isbn_ok(x) for x in tokens):
                out.append(issue("ISBN_CHECKSUM", "error", "isbn", f"Неверная контрольная цифра ISBN: {value[:30]}"))
        if not f.get("pages") and not rec.get("in_press"):
            out.append(issue("PAGES_MISSING", "warn", "pages", "Страницы не указаны"))
        haystack = " ".join([f.get("source", ""), f.get("title", "")])
        if attrs.get("place") == "kz" and FOREIGN_SIGNS.search(haystack):
            out.append(issue("PLACE_MISMATCH", "error", "place", "Похоже, конференция прошла за рубежом, но запись стоит в разделе «в РК»"))
        if JOURNAL_SIGNS.search(f.get("source", "")) and "конференц" not in f.get("source", "").lower():
            out.append(issue("JOURNAL_IN_CONFERENCE", "error", "source", "Похоже на журнал, но запись стоит в разделе конференций"))
        if PORTAL_SIGNS.search(f.get("source", "")):
            out.append(issue("PORTAL_IN_CONFERENCE", "warn", "source", "Похоже на информационный портал, а не на сборник конференции"))
    if t == "monograph":
        value = f.get("isbn", "")
        if not value:
            out.append(issue("ISBN_MISSING", "warn", "isbn", "ISBN не указан"))
        else:
            tokens = extract_isbn(value)
            if tokens and not all(isbn_ok(x) for x in tokens):
                out.append(issue("ISBN_CHECKSUM", "error", "isbn", f"Неверная контрольная цифра ISBN: {value[:30]}"))
        if not f.get("sheets"):
            out.append(issue("SHEETS_MISSING", "info", "sheets", "Не указано число печатных листов"))
    if t == "prize":
        place = f.get("award_place", "")
        if not place:
            out.append(issue("PRIZE_PLACE_MISSING", "error", "award_place", "Место не указано"))
        else:
            m_place = re.search(r"([123])\s*(?:-?\s*(?:ші|шы)?\s*)?(?:место|орын)", place, re.I)
            m_deg = re.search(r"(перв|втор|трет|1-ші|2-ші|3-ші)", place, re.I)
            if m_place and m_deg:
                deg = {"перв": "1", "1-ші": "1", "втор": "2", "2-ші": "2", "трет": "3", "3-ші": "3"}[m_deg.group(1).lower()]
                if deg != m_place.group(1):
                    out.append(issue("PRIZE_CONFLICT", "error", "award_place",
                                     f"«{m_place.group(1)} место» и «диплом {deg} степени» не совпадают"))
        if not f.get("link"):
            out.append(issue("LINK_MISSING", "info", "link", "Нет сайта организатора"))
    if t == "scholarship":
        if attrs.get("place") == "abroad" and re.search(r"астана|алматы|казахстан|қазақстан|комитет науки", " ".join([f.get("venue", ""), f.get("contest", "")]), re.I):
            out.append(issue("PLACE_MISMATCH", "error", "place", "Грант в Казахстане стоит в разделе «зарубежные премии»"))
    if rec.get("in_press"):
        out.append(issue("IN_PRESS", "info", "pages", "В печати: после выхода нужно обновить страницы"))
    if EXCEL_DATE.match(f.get("issue", "") or ""):
        out.append(issue("ISSUE_DATE", "warn", "issue", "На месте номера журнала стоит дата Excel"))
    reported_department = f.get("_reported_department")
    if reported_department and reported_department.strip() != "Менеджмент":
        out.append(issue("DEPARTMENT_TYPO", "info", "department", f"Название кафедры написано с ошибкой: «{reported_department}»"))
    if watchlist and t == "article":
        issns = set(extract_issn(f.get("issn", "")))
        for j in watchlist:
            if j["issn"].replace("-", "") in issns or (j.get("name") and j["name"].lower() == (f.get("source") or "").lower()):
                out.append(issue("JOURNAL_RISK", "error", "source", f"Риск журнала: {j['reason']}"))
    return out


def check_collection(records: list[dict]) -> dict[str, list[dict]]:
    """Жазбалар арасындағы тексеру: ортақ ISBN, бет қиылысуы, бір журналдың екі ISSN-і."""
    result: dict[str, list[dict]] = defaultdict(list)
    by_isbn: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        if r["type"] == "conference":
            for token in extract_isbn(r["fields"].get("isbn", "")):
                by_isbn[token].append(r)
    for token, group in by_isbn.items():
        names: dict[str, list[dict]] = defaultdict(list)
        for r in group:
            key = conference_key(r["fields"].get("source", ""))
            names[key].append(r)
        if len(names) > 1:
            for r in group:
                result[r["id"]].append(issue("ISBN_SHARED", "warn", "isbn", "Один ISBN указан в двух разных сборниках"))
        ranges = []
        for r in group:
            pr = page_range(r["fields"].get("pages", ""))
            if pr:
                ranges.append((pr, r))
        ranges.sort(key=lambda x: x[0])
        for (a, ra), (b, rb) in zip(ranges, ranges[1:]):
            if b[0] < a[1] and norm_title(ra["fields"].get("title", "")) != norm_title(rb["fields"].get("title", "")):
                for r in (ra, rb):
                    result[r["id"]].append(issue("PAGE_OVERLAP", "warn", "pages", "Страницы пересекаются с другой статьёй этого сборника"))
    return result


def conference_key(source: str) -> str:
    text = norm_title(source)
    if "ylym" in text or "ғылым" in text or "bіlіm" in text or "bilim" in text:
        return "gylym"
    return text[:40]


def find_duplicates(records: list[dict]) -> list[dict]:
    """Бір мақала бірнеше рет жазылған топтарды табады."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        if r["type"] in ("article", "conference", "monograph") and not r.get("merged_into"):
            key = norm_title(r["fields"].get("title", ""))
            if len(key) > 15:
                groups[key].append(r)
    out = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
        pages = {page_range(r["fields"].get("pages", "")) for r in group}
        pages.discard(None)
        same_pages = len(pages) <= 1
        sections = {r["section"] for r in group if r.get("section")}
        prefixes = {s[0] for s in sections}
        if len(prefixes) > 1 and same_pages:
            kind = "cross_role"
            text = "Одна статья стоит в разделах разных статусов. Она объединяется в одну запись и видна в обоих разделах."
        elif same_pages and len(sections) == 1:
            kind = "exact"
            text = "Полный повтор в одном разделе."
        elif same_pages:
            kind = "cross_section"
            text = "Одна статья стоит в двух разделах."
        elif len(sections) == 1 and r_authors_differ(group):
            kind = "similar"
            text = "Названия совпадают, но авторы и страницы разные. Нужна проверка человеком."
        else:
            kind = "conflict"
            text = "Одна статья стоит в двух разделах с разными данными."
        out.append({"key": key, "kind": kind, "text": text, "record_ids": [r["id"] for r in group]})
    return out


def r_authors_differ(group: list[dict]) -> bool:
    sets = {tuple(sorted(r.get("author_ids", []))) for r in group}
    return len(sets) > 1

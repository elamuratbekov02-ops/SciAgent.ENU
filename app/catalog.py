"""8 жазба түрі, олардың өрістері және есеп бөліміне бағыттау ережелері."""
from __future__ import annotations

ROLE_LABELS = {
    "teacher": "Преподаватель",
    "doctoral": "Докторант",
    "master": "Магистрант",
    "student": "Студент",
    "external": "Внешний автор",
}
LEARNER_PREFIX = {"student": "3", "master": "4", "doctoral": "5"}
ROLE_BY_PREFIX = {"1": "teacher", "2": "teacher", "3": "student", "4": "master", "5": "doctoral"}

INDEX_LABELS = {
    "wos": "Web of Science",
    "scopus": "Scopus",
    "koksnvo": "КОКСНВО",
    "foreign_other": "Зарубежный журнал (РИНЦ и др.)",
    "other": "Журнал вне перечня КОКСНВО",
}
PLACE_LABELS = {"kz": "Казахстан", "abroad": "Зарубежье"}
REGION_LABELS = {"kz": "Казахстан", "cis": "СНГ", "abroad": "Зарубежье (вне СНГ)"}
LANGUAGE_LABELS = {"kk": "Казахский", "ru": "Русский", "foreign": "Иностранный"}
AWARD_SUBTYPES = {
    "state": "Государственная награда",
    "honorary": "Почётное звание",
    "ministry_badge": "Ведомственная награда",
    "best_teacher": "Лучший преподаватель вуза",
    "academy": "Членство в академии",
    "intl_title": "Международное звание или диплом",
    "ministry_letter": "Грамота министерства",
}
EVENT_RISK = ("boston", "harvard", " us ", "usa", "сша", "рф,", "москва", "екатеринбург", "бишкек", "кр,")

TYPES = {
    "article": {
        "label": "Статья",
        "icon": "fa-file-lines",
        "chat_hint": "PDF или DOI",
        "fields": [
            {"key": "title", "label": "Название публикации", "required": True, "wide": True},
            {"key": "source", "label": "Название журнала", "required": True, "wide": True},
            {"key": "year", "label": "Год", "required": True, "kind": "number"},
            {"key": "issue", "label": "Номер журнала"},
            {"key": "pages", "label": "Страницы", "required": True},
            {"key": "issn", "label": "ISSN", "required": True},
            {"key": "doi", "label": "DOI"},
            {"key": "impact", "label": "Импакт-фактор или ссылка"},
            {"key": "quartile", "label": "Квартиль, процентиль"},
        ],
        "attrs": [{"key": "index", "label": "Индекс", "options": INDEX_LABELS, "required": True}],
    },
    "conference": {
        "label": "Материалы конференции",
        "icon": "fa-people-group",
        "chat_hint": "PDF или ссылка на сборник",
        "fields": [
            {"key": "title", "label": "Название публикации", "required": True, "wide": True},
            {"key": "source", "label": "Полное название сборника", "required": True, "wide": True},
            {"key": "year", "label": "Год", "required": True, "kind": "number"},
            {"key": "issue", "label": "Номер"},
            {"key": "pages", "label": "Страницы", "required": True},
            {"key": "isbn", "label": "ISBN", "required": True},
            {"key": "country", "label": "Страна"},
            {"key": "link", "label": "Сайт организатора"},
        ],
        "attrs": [{"key": "place", "label": "Место проведения", "options": PLACE_LABELS, "required": True}],
    },
    "monograph": {
        "label": "Монография",
        "icon": "fa-book",
        "chat_hint": "Титульный лист или ISBN",
        "fields": [
            {"key": "title", "label": "Название", "required": True, "wide": True},
            {"key": "publisher", "label": "Издательство", "required": True},
            {"key": "city", "label": "Город", "required": True},
            {"key": "sheets", "label": "Печатных листов"},
            {"key": "isbn", "label": "ISBN", "required": True},
            {"key": "grif", "label": "Гриф МНВО"},
        ],
        "attrs": [
            {"key": "place", "label": "Место издания", "options": PLACE_LABELS, "required": True},
            {"key": "language", "label": "Язык", "options": LANGUAGE_LABELS, "required": True},
        ],
    },
    "prize": {
        "label": "Призовое место",
        "icon": "fa-trophy",
        "chat_hint": "Фото диплома",
        "fields": [
            {"key": "event", "label": "Название конференции или конкурса", "required": True, "wide": True},
            {"key": "award_place", "label": "Дата и место (I, II, III)", "required": True},
            {"key": "venue", "label": "Место проведения", "required": True},
            {"key": "group", "label": "Группа, курс"},
            {"key": "phone", "label": "Телефон", "pii": True},
            {"key": "email", "label": "Email", "pii": True},
            {"key": "link", "label": "Сайт организатора"},
        ],
        "attrs": [{"key": "region", "label": "Регион", "options": REGION_LABELS, "required": True}],
    },
    "award": {
        "label": "Награда, звание",
        "icon": "fa-medal",
        "chat_hint": "Удостоверение или грамота",
        "fields": [
            {"key": "award_name", "label": "Название награды", "required": True, "wide": True},
            {"key": "degree", "label": "Учёная степень"},
            {"key": "position", "label": "Должность"},
            {"key": "org", "label": "Выдавшая организация"},
            {"key": "country", "label": "Страна"},
            {"key": "date", "label": "Дата присуждения", "required": True},
        ],
        "attrs": [{"key": "subtype", "label": "Вид", "options": AWARD_SUBTYPES, "required": True}],
    },
    "scholarship": {
        "label": "Премия, стипендия, грант",
        "icon": "fa-award",
        "chat_hint": "Договор или сертификат",
        "fields": [
            {"key": "contest", "label": "Название конкурса, организации", "required": True, "wide": True},
            {"key": "result", "label": "Результат, название проекта", "wide": True},
            {"key": "degree", "label": "Учёная степень"},
            {"key": "position", "label": "Должность"},
            {"key": "date", "label": "Дата", "required": True},
            {"key": "venue", "label": "Место проведения"},
        ],
        "attrs": [{"key": "place", "label": "Регион", "options": PLACE_LABELS, "required": True}],
    },
    "editorial": {
        "label": "Редколлегия",
        "icon": "fa-pen-nib",
        "chat_hint": "Ссылка на журнал",
        "fields": [
            {"key": "journal", "label": "Название журнала", "required": True, "wide": True},
            {"key": "degree", "label": "Учёная степень"},
            {"key": "position", "label": "Должность"},
            {"key": "period", "label": "Период", "required": True},
        ],
        "attrs": [{"key": "indexed", "label": "Журнал в WoS или Scopus?",
                   "options": {"yes": "Да", "no": "Нет"}, "required": True}],
    },
    "project": {
        "label": "Участие в проекте",
        "icon": "fa-diagram-project",
        "chat_hint": "Приказ или текст",
        "fields": [
            {"key": "project", "label": "Название проекта", "required": True, "wide": True},
            {"key": "project_role", "label": "Должность в проекте", "required": True},
            {"key": "participation", "label": "Степень участия"},
            {"key": "project_lead", "label": "Руководитель проекта", "required": True},
            {"key": "group", "label": "Группа, курс"},
        ],
        "attrs": [],
    },
    "textbook": {
        "label": "Учебник, пособие",
        "icon": "fa-book-open",
        "chat_hint": "Титульный лист или ISBN",
        "fields": [
            {"key": "title", "label": "Название", "required": True, "wide": True},
            {"key": "publisher", "label": "Издательство"},
            {"key": "year", "label": "Год", "required": True, "kind": "number"},
            {"key": "sheets", "label": "Печатных листов"},
            {"key": "isbn", "label": "ISBN"},
        ],
        "attrs": [],
    },
    "patent": {
        "label": "Авторское свидетельство, патент",
        "icon": "fa-certificate",
        "chat_hint": "Свидетельство или патент",
        "fields": [
            {"key": "title", "label": "Название", "required": True, "wide": True},
            {"key": "number", "label": "Номер документа"},
            {"key": "year", "label": "Год", "required": True, "kind": "number"},
            {"key": "link", "label": "Ссылка"},
        ],
        "attrs": [],
    },
}

# Жарияланымның үйі: Smart.ENU «Научные работы». Модуль оларды сол жерден алады, ал қалған нәтижелер модульге енгізіледі.
WORK_RECORD_TYPES = ("article", "conference", "monograph", "textbook", "patent")
# Ф ЕНУ 605-02-25 нысанында оқулық пен патент тізімі жоқ: олар «Научные работы» бетінде қалады, есепке кірмейді.
OUTSIDE_FORM_TYPES = ("textbook", "patent")
WORK_TYPES = {
    "textbook": {"label": "Учебники / учебные пособия / методические пособия / семинары", "type": "textbook", "attrs": {}},
    "monograph": {"label": "Монография", "type": "monograph", "attrs": {}},
    "wos": {"label": "Статьи в международных рецензируемых журналах Web of Science Core Collection", "type": "article", "attrs": {"index": "wos"}},
    "authority": {"label": "В изданиях, рекомендованных уполномоченным органом", "type": "article", "attrs": {"index": "koksnvo"}},
    "conference": {"label": "В сборниках международных научно-практических конференций", "type": "conference", "attrs": {}},
    "patent": {"label": "Авторские свидетельства, патенты", "type": "patent", "attrs": {}},
    "koksnvo": {"label": "Научное издание, рекомендованное КОКСНВО", "type": "article", "attrs": {"index": "koksnvo"}},
    "other": {"label": "Другое", "type": "article", "attrs": {}},
}
WORK_LABEL_SCOPUS = "Статьи Scopus (импорт из Scopus)"
_WORK_FORM = {
    "article": ("title", "source", "year", "issue", "pages", "issn", "doi"),
    "conference": ("title", "source", "year", "issue", "pages", "isbn", "link"),
    "monograph": ("title", "publisher", "city", "year", "sheets", "isbn"),
    "textbook": ("title", "publisher", "year", "sheets", "isbn"),
    "patent": ("title", "number", "year", "link"),
}


def work_form(key: str) -> dict:
    """«Добавить научную работу» терезесі. Міндетті өріс екеу, есепке керегінің қалғанын модуль кейін сұрайды."""
    spec = WORK_TYPES[key]
    labels = {f["key"]: f["label"] for f in TYPES[spec["type"]]["fields"]}
    return {"label": spec["label"], "fields": [{"key": k, "label": labels.get(k, "Год"), "required": k in ("title", "year")} for k in _WORK_FORM[spec["type"]]]}


def work_type_of(rec: dict) -> str | None:
    """Жазбаның «Научные работы» тізіміндегі түрі. None болса, жазба тек модульде сақталады."""
    if rec.get("type") not in WORK_RECORD_TYPES:
        return None
    if rec.get("work_type") in WORK_TYPES:
        return rec["work_type"]
    if rec["type"] == "article":
        return {"wos": "wos", "scopus": "scopus", "koksnvo": "koksnvo"}.get(rec.get("attrs", {}).get("index"), "other")
    return rec["type"]


def work_type_label(rec: dict) -> str:
    key = work_type_of(rec)
    return WORK_LABEL_SCOPUS if key == "scopus" else WORK_TYPES[key]["label"] if key else ""


SMARTENU_TYPE = {
    ("article", "wos"): "article",
    ("article", "scopus"): "scopus_article",
    ("article", "koksnvo"): "publication_koksnvo",
    ("article", "foreign_other"): "free",
    ("article", "other"): "free",
    ("conference", None): "conference_proceedings",
    ("monograph", None): "monograph",
}
SMARTENU_FIELDS = {
    "title": "publicationName", "year": "publicationDate", "source": "editionName",
    "issue": "editionNumber", "pages": "editionPages", "issn": "issn", "isbn": "isbn",
    "doi": "link", "link": "link", "sheets": "printedPages", "publisher": "editionName",
}

MONOGRAPH_ROUTE = {
    ("kz", "kk"): "2.7", ("kz", "ru"): "2.8", ("abroad", "foreign"): "2.9",
    ("kz", "foreign"): "2.10", ("abroad", "kk"): "2.11", ("abroad", "ru"): "2.12",
}
AWARD_ROUTE = {
    "state": "1.1", "honorary": "1.2", "ministry_badge": "1.3", "best_teacher": "1.4",
    "academy": "1.5", "intl_title": "1.6", "ministry_letter": "1.7",
}


def route(rec_type: str, role: str, attrs: dict) -> str | None:
    """Жазба түрі, автор мәртебесі және белгілер бойынша есеп бөлімін анықтайды."""
    attrs = attrs or {}
    if rec_type == "article":
        index = attrs.get("index")
        if role == "teacher":
            return {"wos": "2.2", "scopus": "2.3", "foreign_other": "2.4а",
                    "koksnvo": "2.4б", "other": "2.4в"}.get(index)
        prefix = LEARNER_PREFIX.get(role)
        if not prefix:
            return None
        return {"wos": f"{prefix}.1", "scopus": f"{prefix}.2", "foreign_other": f"{prefix}.3а",
                "koksnvo": f"{prefix}.3б", "other": f"{prefix}.3в"}.get(index)
    if rec_type == "conference":
        place = attrs.get("place", "kz")
        if role == "teacher":
            return "2.5" if place == "kz" else "2.6"
        prefix = LEARNER_PREFIX.get(role)
        return (f"{prefix}.4" if place == "kz" else f"{prefix}.5") if prefix else None
    if rec_type == "monograph":
        return MONOGRAPH_ROUTE.get((attrs.get("place"), attrs.get("language")))
    if rec_type == "prize":
        prefix = LEARNER_PREFIX.get(role)
        if not prefix:
            return None
        return {"kz": f"{prefix}.6", "cis": f"{prefix}.7", "abroad": f"{prefix}.8"}.get(attrs.get("region"))
    if rec_type == "award":
        return AWARD_ROUTE.get(attrs.get("subtype"))
    if rec_type == "scholarship":
        return "1.8" if attrs.get("place") == "kz" else "1.9"
    if rec_type == "editorial":
        return "2.13" if attrs.get("indexed") == "yes" else "2.14"
    if rec_type == "project":
        return {"master": "4.9", "doctoral": "5.9"}.get(role)
    return None


def attrs_from_block(bid: str) -> tuple[str, str, dict]:
    """Бөлім нөмірінен жазба түрін, рөлді және белгілерді қайта шығарады (импортқа керек)."""
    role = ROLE_BY_PREFIX.get(bid[0], "teacher")
    if bid.startswith("1."):
        n = int(bid.split(".")[1])
        if n <= 7:
            sub = {v: k for k, v in AWARD_ROUTE.items()}[bid]
            return "award", "teacher", {"subtype": sub}
        return "scholarship", "teacher", {"place": "kz" if bid == "1.8" else "abroad"}
    if bid.startswith("2."):
        tail = bid[2:]
        if tail in ("2", "3", "4а", "4б", "4в"):
            index = {"2": "wos", "3": "scopus", "4а": "foreign_other", "4б": "koksnvo", "4в": "other"}[tail]
            return "article", role, {"index": index}
        if tail in ("5", "6"):
            return "conference", role, {"place": "kz" if tail == "5" else "abroad"}
        if tail in ("7", "8", "9", "10", "11", "12"):
            place, lang = next(k for k, v in MONOGRAPH_ROUTE.items() if v == bid)
            return "monograph", role, {"place": place, "language": lang}
        return "editorial", role, {"indexed": "yes" if tail == "13" else "no"}
    tail = bid[2:]
    if tail in ("1", "2", "3а", "3б", "3в"):
        index = {"1": "wos", "2": "scopus", "3а": "foreign_other", "3б": "koksnvo", "3в": "other"}[tail]
        return "article", role, {"index": index}
    if tail in ("4", "5"):
        return "conference", role, {"place": "kz" if tail == "4" else "abroad"}
    if tail in ("6", "7", "8"):
        return "prize", role, {"region": {"6": "kz", "7": "cis", "8": "abroad"}[tail]}
    return "project", role, {}


def display_title(record: dict) -> str:
    f = record.get("fields", {})
    return (f.get("title") or f.get("event") or f.get("award_name") or f.get("contest") or
            f.get("journal") or f.get("project") or "(без названия)")

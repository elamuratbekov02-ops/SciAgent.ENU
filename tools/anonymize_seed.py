"""Демо-деректегі білім алушылардың нақты атын шартты атпен ауыстырады.

Студент, магистрант және докторант «Студент-07» түріндегі атпен көрсетіледі. Демо иесі, оқытушылар және
сыртқы авторлар өзгермейді. Жеке адамға апаратын сілтемелер (әлеуметтік желі, жаңалық беті) де алынады.
Сандар мен бөлімдер өзгермейді, сондықтан есеп пен аналитика бұрынғыдай шығады.

Қолданылуы:  python tools/anonymize_seed.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "data" / "seed.json"

LABELS = {"student": ("Студент", "Student"), "master": ("Магистрант", "Master"), "doctoral": ("Докторант", "Doctoral")}
LETTERS = "A-Za-zА-ЯЁа-яёӘәҒғҚқҢңӨөҰұҮүІіҺһ"
# Аттан кейін әріп те, тағы бір инициал да келмейді: басқа адамның «Аты Ж.Б.» жазуы «Аты Ж» нұсқасына сәйкес келмеуі керек.
NAME_END = rf"(?![{LETTERS}])(?!\.\s*[A-ZА-ЯЁӘҒҚҢӨҰҮІҺ]\.)"
HIDDEN_LINK = "https://example.edu/link-hidden"
PRIVATE_LINK = re.compile(r"instagram\.com|facebook\.com|vk\.com|t\.me/|/news/", re.I)
_ANY_LABEL = "|".join(name for pair in LABELS.values() for name in pair)
TITLE_PREFIX = re.compile(rf"^(?:{_ANY_LABEL})-\d+\s+")
ALREADY_HIDDEN = re.compile(rf"^(?:{_ANY_LABEL})-\d+$")


def hidden_people(seed: dict) -> list[dict]:
    """Демо иесі мен ойдан шығарылған үлгі адамнан басқа барлық білім алушы."""
    owner = next(p["person"] for p in seed["positions"] if p["id"] == "doctoral")
    return [p for p in seed["persons"] if p["role"] in LABELS and p["id"] != owner and not p.get("sample")]


def pseudonyms(seed: dict) -> dict[str, tuple[str, str]]:
    counters = dict.fromkeys(LABELS, 0)
    out = {}
    for person in hidden_people(seed):
        counters[person["role"]] += 1
        cyr, lat = LABELS[person["role"]]
        out[person["id"]] = (f"{cyr}-{counters[person['role']]:02d}", f"{lat}-{counters[person['role']]:02d}")
    return out


def _is_latin(name: str) -> bool:
    return not re.search(r"[А-ЯЁа-яёӘәҒғҚқҢңӨөҰұҮүІіҺһ]", name)


def _flexible(name: str) -> str:
    """«Аты Ж.Б.» жазылымындағы бос орын мен нүкте айырмашылығын елемейді."""
    parts = re.findall(rf"[{LETTERS}'’\-]+|\.", name)
    body = ""
    for part in parts:
        body += r"\.?\s*" if part == "." else re.escape(part) + r"\s*"
    return rf"(?<![{LETTERS}])(?<![{LETTERS}]\.)(?i:{body.rstrip('*').removesuffix(chr(92) + 's')}){NAME_END}"


def rules(seed: dict) -> list[tuple[str, str]]:
    """Ауыстыру ережелері, ең ұзын атау алдымен. Басқа адамға ортақ атау ережеге кірмейді."""
    hidden = {p["id"] for p in hidden_people(seed)}
    names = pseudonyms(seed)

    def variants(person: dict) -> set[str]:
        raw = [person.get("full_name"), person.get("display_name"), person.get("display_latin"), *(person.get("aliases") or [])]
        return {x.strip() for x in raw if x and x.strip()}

    keep_names: set[str] = set()
    keep_words: set[str] = set()
    for person in seed["persons"]:
        if person["id"] not in hidden:
            keep_names |= variants(person)
            for name in variants(person):
                keep_words |= set(re.findall(rf"[{LETTERS}'’\-]+", name))
    full: dict[str, str] = {}
    surnames: dict[str, str] = {}
    for person in hidden_people(seed):
        if ALREADY_HIDDEN.match(person["display_name"]):
            continue
        cyr, lat = names[person["id"]]
        for name in variants(person) - keep_names:
            full[name] = lat if _is_latin(name) else cyr
        for name in (person.get("display_name"), person.get("display_latin"), person.get("full_name")):
            surname = name.split()[0] if name else ""
            if len(surname) >= 4 and surname not in keep_words:
                surnames[surname] = lat if _is_latin(surname) else cyr
    # Алдымен толық аты-жөн, содан кейін тек тегі: әйтпесе мәтінде жеке есім қалып қояды.
    found = [(_flexible(name), full[name]) for name in sorted(full, key=len, reverse=True)]
    for surname in sorted(surnames, key=len, reverse=True):
        up = "A-Z" if _is_latin(surname) else "А-ЯЁӘҒҚҢӨҰҮІҺ"
        found.append((rf"(?<![{LETTERS}])(?:[{up}]\.\s*){{0,3}}(?i:{re.escape(surname)})(?:\s+[{up}]\.?(?:\s*[{up}]\.?){{0,2}})?{NAME_END}", surnames[surname]))
    return found


def replace_text(text: str, compiled: list[tuple[re.Pattern, str]]) -> str:
    for rx, new in compiled:
        text = rx.sub(new, text)
    return text


def _tidy(text: str) -> str:
    """Аты-жөннен қалған нүктені алып, шартты аттарды үтірмен бөледі."""
    label = rf"(?:{_ANY_LABEL})-\d+"
    text = re.sub(rf"({label})\s*\.\s*(?=[,;]|$)", r"\1", text)
    text = re.sub(rf"({label})\s*\.\s*", r"\1 ", text)
    text = re.sub(rf"({label})\s+(?={label})", r"\1, ", text)
    return re.sub(rf"^\.\s*(?={label})", "", text)


def anonymize(seed: dict) -> dict:
    compiled = [(re.compile(rx), new) for rx, new in rules(seed)]
    names = pseudonyms(seed)
    records = json.loads(replace_text(json.dumps(seed["records"], ensure_ascii=False), compiled))
    for rec in records:
        fields = rec["fields"]
        if fields.get("title"):
            fields["title"] = TITLE_PREFIX.sub("", fields["title"])
        if PRIVATE_LINK.search(fields.get("link") or ""):
            fields["link"] = HIDDEN_LINK
        if fields.get("authors_text"):
            fields["authors_text"] = _tidy(fields["authors_text"])
    seed["records"] = records
    for person in seed["persons"]:
        if person["id"] in names:
            cyr, lat = names[person["id"]]
            person.update(display_name=cyr, display_latin=lat, full_name="", aliases=[cyr, lat])
    return seed


def main() -> None:
    seed = anonymize(json.loads(SEED.read_text(encoding="utf-8")))
    SEED.write_text(json.dumps(seed, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Шартты атқа ауыстырылды:", len(hidden_people(seed)))


if __name__ == "__main__":
    main()

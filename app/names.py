"""Авторды сәйкестендіру: транслитерация, есім бөлу, жетекшіні табу."""
from __future__ import annotations

import re
import unicodedata

TRANSLIT = {
    "а": "a", "ә": "a", "б": "b", "в": "v", "г": "g", "ғ": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "і": "i", "к": "k", "қ": "k", "л": "l", "м": "m",
    "н": "n", "ң": "n", "о": "o", "ө": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ұ": "u", "ү": "u", "ф": "f", "х": "kh", "һ": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

UP = "A-ZА-ЯЁӘІҢҒҮҰҚӨҺ"
LOW = "a-zа-яёәіңғүұқөһ"

SUPERVISOR_RX = re.compile(
    rf"(?:ғылыми\s+жет[еe][кқ]\w*|научн\w*\s+рук\w*|scientific\s+advisor|supervisor)\s*[:\-–]?\s*(.*)$",
    re.I | re.S,
)


def translit(text: str) -> str:
    out = []
    for ch in text.lower():
        out.append(TRANSLIT.get(ch, ch))
    return "".join(out)


def surname_key(surname: str) -> str:
    key = translit(surname)
    key = unicodedata.normalize("NFKD", key)
    key = re.sub(r"[^a-z0-9]", "", key)
    # Латын мен кириллица жазылымындағы ұсақ айырмашылықтарды жою
    key = key.replace("yu", "u").replace("ye", "e").replace("iy", "i").replace("yi", "i")
    key = key.replace("y", "i").replace("kh", "h").replace("zh", "j")
    return key


def levenshtein(a: str, b: str, limit: int = 3) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


_INITIAL = rf"[{UP}][{LOW}]?\."
# Шартты ат («Студент-07») нөмірмен аяқталады, ал аты-жөн соңындағы сілтеме цифры («Әлиев1») атқа кірмейді.
_SURNAME = rf"[{UP}][{LOW}'’\-]{{2,}}(?:(?<=-)\d{{2}})?"
_I_THEN_S = re.compile(rf"((?:{_INITIAL}\s*){{1,3}})\s*({_SURNAME})")
_S_THEN_I = re.compile(rf"({_SURNAME})\s+((?:[{UP}]\.?\s*){{1,3}})(?=$|[\s,.;])")
_FULL = re.compile(rf"({_SURNAME})((?:\s+{_SURNAME}){{1,2}})")


def _initials(raw: str) -> str:
    letters = re.findall(rf"[{UP}]", raw or "")
    return "".join(letters[:2])


def parse_people(text: str) -> list[dict]:
    """«Сурname И.И.» түріндегі мәтінді адамдар тізіміне бөледі."""
    if not text:
        return []
    cleaned = re.sub(r"\(.*?\)", " ", text)
    cleaned = re.sub(rf"([{LOW}])([{UP}]\.)", r"\1 \2", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,;")
    people: list[dict] = []
    for chunk in re.split(r"[,;/]| и | және ", cleaned):
        chunk = chunk.strip(" .")
        if len(chunk) < 2:
            continue
        pos = 0
        found = False
        while pos < len(chunk):
            rest = chunk[pos:]
            a = _I_THEN_S.search(rest)
            b = _S_THEN_I.search(rest)
            c = _FULL.search(rest)
            options = [(m.start(), k, m) for k, m in (("a", a), ("b", b), ("c", c)) if m]
            if not options:
                break
            options.sort(key=lambda x: (x[0], {"b": 0, "a": 1, "c": 2}[x[1]]))
            _, kind, m = options[0]
            raw = m.group(0).strip()
            if kind == "a":
                people.append({"surname": m.group(2), "initials": _initials(m.group(1)), "raw": raw})
            elif kind == "b":
                people.append({"surname": m.group(1), "initials": _initials(m.group(2)), "raw": raw})
            else:
                people.append({"surname": m.group(1), "initials": _initials(m.group(2)), "raw": raw, "full": True,
                               "other": m.group(2).split()[0]})
            pos += m.end()
            found = True
        if not found:
            token = chunk.split()[0] if chunk.split() else ""
            if re.fullmatch(_SURNAME, token):
                people.append({"surname": token, "initials": "", "raw": token})
    return people


def split_authors_supervisor(text: str) -> tuple[str, str]:
    """Автор ұяшығынан «Ғылыми жетекші: ...» бөлігін бөліп алады."""
    if not text:
        return "", ""
    m = SUPERVISOR_RX.search(text)
    if not m:
        return text.strip(), ""
    return text[: m.start()].strip(" ,.;"), m.group(1).strip(" ,.:;")


def same_person(a: dict, b: dict) -> bool:
    ka, kb = surname_key(a["surname"]), surname_key(b["surname"])
    if not ka or not kb:
        return False
    if ka != kb and (re.search(r"\d", ka) or re.search(r"\d", kb)):
        return False
    limit = 0 if min(len(ka), len(kb)) < 6 else 1 if min(len(ka), len(kb)) < 9 else 2
    if levenshtein(ka, kb, 3) > limit:
        return False
    ia, ib = a.get("initials") or "", b.get("initials") or ""
    if ia and ib:
        return surname_key(ia[0]) == surname_key(ib[0])
    return True


def match_person(raw_name: str, directory: list[dict]) -> dict:
    """Анықтамалықтан адам іздейді. Деректі сервер ішінде ғана салыстырады."""
    parsed = parse_people(raw_name)
    if not parsed:
        return {"raw": raw_name, "person_id": None, "score": 0.0}
    target = parsed[0]
    best, score = None, 0.0
    for person in directory:
        for alias in person.get("aliases", []) or [person["display_name"]]:
            candidates = parse_people(alias)
            if not candidates:
                continue
            cand = candidates[0]
            if not same_person(target, cand):
                continue
            ka, kb = surname_key(target["surname"]), surname_key(cand["surname"])
            s = 1.0 - levenshtein(ka, kb, 3) * 0.08
            if target.get("initials") and cand.get("initials") and target["initials"][:2] == cand["initials"][:2]:
                s = min(1.0, s + 0.05)
            elif not target.get("initials"):
                s -= 0.1
            if s > score:
                best, score = person, s
    return {"raw": raw_name, "person_id": best["id"] if best else None, "score": round(score, 2)}


def norm_title(text: str) -> str:
    text = (text or "").lower()
    return re.sub(r"[^0-9a-zа-яёәіңғүұқөһ]+", "", text)


def is_kazakh(text: str) -> bool:
    return bool(re.search(r"[әіңғүұқөһӘІҢҒҮҰҚӨҺ]", text or ""))

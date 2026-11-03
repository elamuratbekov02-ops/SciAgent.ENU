"""Демо-дерек ережесін тексереді. Шығыста аттар емес, тек сандар көрсетіледі.

Ереже: есептегі телефон мен email қосылмайды; нақты адамға жасанды дәреже мен топ тағылмайды;
ойдан шығарылған жарияланымның атауы «[Пример]» деп басталады; білім алушы шартты атпен көрсетіледі.

Қолданылуы:  python tools/check_seed_privacy.py "<есеп.xlsx>"
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from anonymize_seed import ALREADY_HIDDEN, hidden_people  # noqa: E402
from app.form_parser import read_blocks  # noqa: E402


def main(path: str) -> int:
    parsed = read_blocks(path)
    contacts = set()
    for block in parsed["blocks"]:
        cols = {c["col"]: c["key"] for c in block["header"]}
        for row in block["rows"]:
            for col, value in row.items():
                if cols.get(col) in ("phone", "email"):
                    contacts.add(value)

    failures = 0
    seed_text = (ROOT / "data" / "seed.json").read_text(encoding="utf-8")
    schema_text = (ROOT / "data" / "form_schema.json").read_text(encoding="utf-8")
    seed = json.loads(seed_text)

    for name, text in (("seed.json", seed_text), ("form_schema.json", schema_text)):
        leaked = [c for c in contacts if c and c in text]
        emails = [e for e in re.findall(r"[\w.\-]+@[\w.\-]+", text) if not e.endswith("example.edu")]
        phones = [p for p in re.findall(r"(?:\+?7|8)[\s\-(]*7\d{2}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}", text)]
        print(f"{name}: контакты={len(leaked)}, email={len(emails)}, телефон={len(phones)}")
        failures += len(leaked) + len(emails) + len(phones)

    fake = 0
    for p in seed["persons"]:
        if p.get("sample") or p["role"] == "manager":
            continue
        if p.get("phone") or p.get("email"):
            fake += 1
        if p.get("degree") and not p.get("on_portal"):
            fake += 1
    print("вымышленные сведения у реальных людей:", fake)
    failures += fake

    invented = [c for c in seed["candidates"] if not c["title"].startswith("[Пример]")]
    invented += [i for items in seed["mock_import"].values() for i in items if not i["fields"]["title"].startswith("[Пример]")]
    print("примеры без пометки:", len(invented))
    failures += len(invented)

    tagged = sum(1 for r in seed["records"] if r["attrs"].get("coauthor_kz") or r["attrs"].get("coauthor_foreign"))
    print("вымышленные пометки соавторов:", tagged)
    failures += tagged

    named = [p for p in hidden_people(seed) if not ALREADY_HIDDEN.match(p["display_name"])]
    print("обучающиеся под настоящим именем:", len(named))
    failures += len(named)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))

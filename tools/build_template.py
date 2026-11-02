"""Ресми есептен бос үлгі жасайды: пішім мен тақырыптар қалады, дерек жолдары тазаланады.

Қолданылуы:  python tools/build_template.py "<есеп.xlsx>"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.form_parser import SHEET_ORDER, read_layout  # noqa: E402

CONTACT_HINTS = ("мобильного", "e-mail")


def main(path: str) -> None:
    # Формула сілтейтін жол есепте жылжиды, сондықтан үлгіге дайын мән жазылады.
    wb = load_workbook(path, data_only=True)
    for name in list(wb.sheetnames):
        if name not in SHEET_ORDER:
            del wb[name]
    layout = read_layout(path)
    for name, blocks in layout["sheets"].items():
        ws = wb[name]
        for block in blocks:
            for r in range(block["data_first"], block["next_row"]):
                for cell in ws[r]:
                    if cell.coordinate in ws.merged_cells:
                        continue
                    # Бос жолдағы факультет атауы нысанның өзінде тұр, қалған мәндер дерек.
                    if cell.column_letter == "A" and block["data_count"] == 0:
                        continue
                    cell.value = None
        for r in range(1, ws.max_row + 1):
            for cell in ws[r]:
                if isinstance(cell.value, str) and "@" in cell.value:
                    cell.value = None
    ws = wb["Анализ НИР факультета"]
    for r in range(3, ws.max_row + 1):
        for col in ("B", "C", "D"):
            ws[f"{col}{r}"].value = None
    wb.save(ROOT / "data" / "f605_template.xlsx")
    (ROOT / "data" / "f605_layout.json").write_text(json.dumps(layout, ensure_ascii=False, indent=1), encoding="utf-8")
    print("template saved:", {k: len(v) for k, v in layout["sheets"].items()})


if __name__ == "__main__":
    main(sys.argv[1])

"""Демоға үлгі файлдар жасайды: мақала PDF, диплом мен монография титулының суреті, аудитке арналған есеп.

Файлдардағы барлық адам мен журнал атауы жасанды. Қолданылуы:  python tools/build_samples.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SCIAGENT_DB"] = str(Path(tempfile.mkdtemp()) / "samples.db")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app import reporting, services, store  # noqa: E402

OUT = ROOT / "static" / "samples"
OUT.mkdir(parents=True, exist_ok=True)
FONT = next((p for p in (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf") if Path(p).exists()), None)
FONT_B = next((p for p in (r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf") if Path(p).exists()), FONT)


def wrap(c: canvas.Canvas, text: str, x: float, y: float, width: float, font: str, size: int, leading: int) -> float:
    words, line = text.split(), ""
    c.setFont(font, size)
    for w in words:
        trial = (line + " " + w).strip()
        if c.stringWidth(trial, font, size) > width:
            c.drawString(x, y, line)
            y -= leading
            line = w
        else:
            line = trial
    if line:
        c.drawString(x, y, line)
        y -= leading
    return y


def article_pdf(path: Path, title: str, authors: str, journal: str, issn: str, doi: str, volume: str, pages: str, year: str) -> None:
    pdfmetrics.registerFont(TTFont("Body", FONT))
    pdfmetrics.registerFont(TTFont("Bold", FONT_B))
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    c.setFont("Body", 9)
    c.drawString(50, h - 40, f"{journal} · ISSN {issn} · {year}, {volume} · pp. {pages}")
    c.drawString(50, h - 53, f"DOI: {doi}")
    c.line(50, h - 60, w - 50, h - 60)
    y = wrap(c, title, 50, h - 95, w - 100, "Bold", 15, 19) - 8
    y = wrap(c, authors, 50, y, w - 100, "Body", 11, 14)
    y = wrap(c, "L.N. Gumilyov Eurasian National University, Astana, Kazakhstan", 50, y, w - 100, "Body", 9, 12) - 12
    y = wrap(c, "Abstract", 50, y, w - 100, "Bold", 11, 14)
    y = wrap(c, "This synthetic sample article is used to demonstrate SciAgent.ENU. The agent reads the bibliographic data, "
                "recognises the authors and proposes the report section. All names and journal details in this file are invented.",
             50, y, w - 100, "Body", 10, 13)
    c.showPage()
    c.save()


def diploma_png(path: Path, name: str, group: str) -> None:
    img = Image.new("RGB", (1200, 850), "#fbf7ea")
    d = ImageDraw.Draw(img)
    d.rectangle((30, 30, 1170, 820), outline="#b08a2e", width=6)
    big = ImageFont.truetype(FONT_B, 64)
    mid = ImageFont.truetype(FONT_B, 34)
    small = ImageFont.truetype(FONT, 28)
    def center(text, y, font, fill="#2b2b2b"):
        box = d.textbbox((0, 0), text, font=font)
        d.text(((1200 - box[2]) / 2, y), text, font=font, fill=fill)
    center("ДИПЛОМ", 90, big, "#8a6a14")
    center("II степени", 180, mid)
    center("Условный конкурс научных работ", 280, small)
    center("VII международная олимпиада студентов", 325, small)
    center("награждается:", 420, small)
    center(name, 475, mid)
    center(f"группа: {group}", 535, small)
    center("г. Бишкек, 18.04.2025", 640, small)
    center("Это образец: организация и имя вымышлены", 750, ImageFont.truetype(FONT, 20), "#777777")
    img.save(path)


def monograph_png(path: Path, name: str) -> None:
    img = Image.new("RGB", (900, 1250), "#ffffff")
    d = ImageDraw.Draw(img)
    big = ImageFont.truetype(FONT_B, 40)
    mid = ImageFont.truetype(FONT, 28)
    small = ImageFont.truetype(FONT, 22)
    def center(text, y, font):
        box = d.textbbox((0, 0), text, font=font)
        d.text(((900 - box[2]) / 2, y), text, font=font, fill="#222222")
    center(name, 120, mid)
    center("УПРАВЛЕНЧЕСКИЕ РЕШЕНИЯ", 350, big)
    center("В ЦИФРОВОЙ ЭКОНОМИКЕ", 405, big)
    center("Монография", 490, mid)
    center("Астана: «Издательство Образец», 2025", 1000, small)
    center("ISBN 978-601-7625-79-5", 1040, small)
    center("12,5 п.л.", 1080, small)
    center("Это образец: автор и издательство вымышлены", 1170, ImageFont.truetype(FONT, 18))
    img.save(path)


def main() -> None:
    seed = json.loads((ROOT / "data" / "seed.json").read_text(encoding="utf-8"))
    persons = {p["id"]: p for p in seed["persons"]}
    positions = {p["id"]: p for p in seed["positions"]}
    owner = persons[positions["doctoral"]["person"]]
    # Ойдан шығарылған файлға нақты адамның аты жазылмайды: автор тек демо иесі не жасанды адам.
    student = next(p for p in seed["persons"] if p.get("sample"))

    article_pdf(OUT / "1_makala_zhana.pdf", "[Sample] Digital transformation of university research reporting: a process mining approach",
                f"{owner['display_latin']}, A. Example", "Journal of Example Higher Education Studies", "2146-4553",
                "10.5555/demo.2025.020", "Vol. 12(2)", "45-58", "2025")
    published = Path.home() / "Downloads" / "2025+1+номер+Экономика+вестник-67-83.pdf"
    if published.exists():
        (OUT / "2_makala_bazada_bar.pdf").write_bytes(published.read_bytes())
    diploma_png(OUT / "3_diplom.png", student["display_name"], student.get("group") or "МН-31")
    monograph_png(OUT / "4_monografiya_tituly.png", "Ульгиев А.Б.")

    store.seed_if_empty(force=True)
    snap = services.snapshot("mgmt", 2025)
    (OUT / "5_audit_uchin_esep.xlsx").write_bytes(reporting.f605_bytes(snap, pii=False))
    files = sorted(p.name for p in OUT.iterdir() if p.name != "index.html")
    links = "\n".join(f'<li><a href="{f}">{f}</a></li>' for f in files)
    (OUT / "index.html").write_text(
        f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Образцы файлов</title>
<style>body{{font:14px/1.6 Inter,Segoe UI,sans-serif;margin:32px;color:#1e293b;background:#fff}}a{{color:#2563eb}}</style></head>
<body><h2>SciAgent.ENU: образцы файлов</h2><p>Скачайте файлы и отправьте их в чат или на страницу «Аудит отчёта». Файлы 1, 3, 4: вымышленные образцы. Файл 2: реальная опубликованная статья, она уже есть в базе. Файл 5: отчёт, сформированный системой.</p>
<ul>{links}</ul></body></html>""", encoding="utf-8")
    print("samples:", files)


if __name__ == "__main__":
    main()

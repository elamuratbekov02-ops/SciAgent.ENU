"""SQLite сақтау қабаты. Жазба өрістері нысанға қарай өзгеретіндіктен JSON ретінде сақталады."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .catalog import route

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = Path(os.environ.get("SCIAGENT_DB", DATA / "sciagent.db"))
UPLOADS = Path(os.environ.get("SCIAGENT_UPLOADS", DATA / "uploads"))

_lock = threading.RLock()
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS units (id TEXT PRIMARY KEY, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS persons (id TEXT PRIMARY KEY, role TEXT, unit TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS supervisions (learner_id TEXT, supervisor_id TEXT, kind TEXT, year INTEGER,
    PRIMARY KEY (learner_id, supervisor_id, kind));
CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, unit TEXT, year INTEGER, type TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candidates (id TEXT PRIMARY KEY, person TEXT, status TEXT, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reports (unit TEXT, year INTEGER, status TEXT, doc TEXT NOT NULL, PRIMARY KEY (unit, year));
CREATE TABLE IF NOT EXISTS report_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, unit TEXT, year INTEGER,
    version INTEGER, approved_by TEXT, approved_at TEXT, snapshot TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaigns (id INTEGER PRIMARY KEY AUTOINCREMENT, year INTEGER, deadline TEXT, title TEXT, created_by TEXT);
CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, person TEXT, role TEXT, unit TEXT,
    text TEXT, link TEXT, at TEXT, read INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, actor TEXT, position TEXT,
    action TEXT, entity TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS audits (id TEXT PRIMARY KEY, at TEXT, doc TEXT NOT NULL);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def upload_path(stored: str) -> Path | None:
    """Жүктелген файлдың жолы. Атауы сервер жасаған үлгіге сай болмаса, қалтадан шықпауы үшін қабылданбайды."""
    if not re.fullmatch(r"[0-9a-f]{24}(\.\w{1,7})?", stored or ""):
        return None
    path = UPLOADS / stored
    return path if path.is_file() else None


def conn() -> sqlite3.Connection:
    """Әр ағынның өз қосылымы бар: бір қосылымды бірге қолдану қатар келген сұраныстарды құлатады."""
    c = getattr(_local, "conn", None)
    if c is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        UPLOADS.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=30)
        c.row_factory = sqlite3.Row
        with _lock:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)
            c.commit()
        _local.conn = c
    return c


def close() -> None:
    c = getattr(_local, "conn", None)
    if c is not None:
        c.close()
        _local.conn = None


def kv_get(key: str, default=None):
    row = conn().execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def kv_set(key: str, value) -> None:
    with _lock:
        conn().execute("INSERT OR REPLACE INTO kv(key,value) VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False)))
        conn().commit()


def seed_if_empty(force: bool = False) -> bool:
    with _lock:
        c = conn()
        has = c.execute("SELECT COUNT(*) n FROM records").fetchone()["n"]
        if has and not force:
            return False
        for table in ("kv", "units", "persons", "supervisions", "records", "candidates", "reports", "report_versions",
                      "campaigns", "notifications", "audit_log", "audits"):
            c.execute(f"DELETE FROM {table}")
        seed = json.loads((DATA / "seed.json").read_text(encoding="utf-8"))
        for u in seed["units"]:
            c.execute("INSERT INTO units(id,doc) VALUES(?,?)", (u["id"], json.dumps(u, ensure_ascii=False)))
        for p in seed["persons"]:
            c.execute("INSERT INTO persons(id,role,unit,doc) VALUES(?,?,?,?)",
                      (p["id"], p["role"], p.get("unit"), json.dumps(p, ensure_ascii=False)))
        for s in seed["supervisions"]:
            c.execute("INSERT OR IGNORE INTO supervisions VALUES(?,?,?,?)",
                      (s["learner_id"], s["supervisor_id"], s["kind"], s["year"]))
        for r in seed["records"]:
            r["roles"] = [r.pop("role")]
            r["sections"] = [r["reported_section"]]
            r["created_at"] = "2025-12-01T09:00:00Z"
            r["updated_at"] = r["created_at"]
            r["evidence"] = []
            r.setdefault("external_authors", [])
            if "_age_days" in r:
                r["stage_since"] = (datetime.now(timezone.utc) - timedelta(days=r.pop("_age_days"))).strftime("%Y-%m-%dT%H:%M:%SZ")
            c.execute("INSERT INTO records(id,unit,year,type,doc) VALUES(?,?,?,?,?)",
                      (r["id"], r["unit"], r["year"], r["type"], json.dumps(r, ensure_ascii=False)))
        for i, cand in enumerate(seed["candidates"], 1):
            cand["id"] = f"c{i:03d}"
            c.execute("INSERT INTO candidates(id,person,status,doc) VALUES(?,?,?,?)",
                      (cand["id"], cand["person"], "pending", json.dumps(cand, ensure_ascii=False)))
        c.commit()
        for key in ("positions", "unit_stats", "analysis_columns", "signers", "shared_between_departments", "mock_import", "school_facts"):
            kv_set(key, seed[key])
        kv_set("settings", {"journal_watchlist": seed["journal_watchlist"],
                            "doctoral_requirements": seed["doctoral_requirements"]})
        kv_set("plan:mgmt:2025", seed["plan"])
        kv_set("manual:mgmt:2025", seed["manual_indicators"])
        kv_set("imported", {})
        # Науқан демода әрқашан ашық тұруы үшін мерзім бүгінгі күннен есептеледі.
        deadline = (datetime.now() + timedelta(days=21)).strftime("%Y-%m-%d")
        c.execute("INSERT INTO campaigns(year,deadline,title,created_by) VALUES(?,?,?,?)",
                  (2025, deadline, "Отчёт НИР за 2025 год", "Департамент науки"))
        stats = {"audit": "согласовано", "tourism": "на согласовании", "acc": "создано", "fin": "согласовано", "econ": "создано"}
        for unit, status in stats.items():
            c.execute("INSERT INTO reports(unit,year,status,doc) VALUES(?,?,?,?)",
                      (unit, 2025, status, json.dumps({"history": [], "synthetic": True}, ensure_ascii=False)))
        c.execute("INSERT INTO reports(unit,year,status,doc) VALUES(?,?,?,?)",
                  ("mgmt", 2025, "создано", json.dumps({"history": []}, ensure_ascii=False)))
        c.commit()
        return True


def log(position: dict, action: str, entity: str = "", detail: str = "") -> None:
    with _lock:
        conn().execute("INSERT INTO audit_log(at,actor,position,action,entity,detail) VALUES(?,?,?,?,?,?)",
                       (now(), position.get("person", ""), position.get("label", ""), action, entity, detail))
        conn().commit()


def logs(limit: int = 200) -> list[dict]:
    rows = conn().execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def units() -> dict[str, dict]:
    return {r["id"]: json.loads(r["doc"]) for r in conn().execute("SELECT * FROM units")}


def persons() -> dict[str, dict]:
    return {r["id"]: json.loads(r["doc"]) for r in conn().execute("SELECT * FROM persons")}


def supervisions() -> list[dict]:
    return [dict(r) for r in conn().execute("SELECT * FROM supervisions")]


def compute_sections(rec: dict) -> list[str]:
    out = []
    for role in rec.get("roles", []):
        section = route(rec["type"], role, rec.get("attrs", {}))
        if section and section not in out:
            out.append(section)
    return out


APPROVED = "согласовано"


def records(unit: str | None = None, year: int | None = None, include_merged: bool = False, approved_only: bool = False) -> list[dict]:
    """approved_only: есеп пен аналитикаға тек келісілген жазба кіреді."""
    sql, args = "SELECT doc FROM records WHERE 1=1", []
    if unit:
        sql += " AND unit=?"
        args.append(unit)
    if year:
        sql += " AND year=?"
        args.append(year)
    out = []
    for row in conn().execute(sql + " ORDER BY id", args):
        doc = json.loads(row["doc"])
        if approved_only and doc.get("status") != APPROVED:
            continue
        if include_merged or not doc.get("merged_into"):
            doc["section"] = doc["sections"][0] if doc.get("sections") else None
            out.append(doc)
    return out


def record(rid: str) -> dict | None:
    row = conn().execute("SELECT doc FROM records WHERE id=?", (rid,)).fetchone()
    if not row:
        return None
    doc = json.loads(row["doc"])
    doc["section"] = doc["sections"][0] if doc.get("sections") else None
    return doc


def save_record(doc: dict) -> dict:
    with _lock:
        doc["updated_at"] = now()
        doc.pop("section", None)
        conn().execute("INSERT OR REPLACE INTO records(id,unit,year,type,doc) VALUES(?,?,?,?,?)",
                       (doc["id"], doc["unit"], doc["year"], doc["type"], json.dumps(doc, ensure_ascii=False)))
        conn().commit()
    doc["section"] = doc["sections"][0] if doc.get("sections") else None
    return doc


def new_record_id() -> str:
    return "r" + uuid.uuid4().hex[:10]


def candidates(person: str | None = None, status: str | None = "pending") -> list[dict]:
    sql, args = "SELECT doc, status FROM candidates WHERE 1=1", []
    if person:
        sql += " AND person=?"
        args.append(person)
    if status:
        sql += " AND status=?"
        args.append(status)
    out = []
    for r in conn().execute(sql, args):
        doc = json.loads(r["doc"])
        doc["status"] = r["status"]
        out.append(doc)
    return out


def add_candidate(doc: dict) -> dict:
    with _lock:
        doc["id"] = "c" + uuid.uuid4().hex[:10]
        conn().execute("INSERT INTO candidates(id,person,status,doc) VALUES(?,?,?,?)",
                       (doc["id"], doc["person"], "pending", json.dumps(doc, ensure_ascii=False)))
        conn().commit()
    return doc


def set_candidate_status(cid: str, status: str) -> dict | None:
    with _lock:
        row = conn().execute("SELECT doc FROM candidates WHERE id=?", (cid,)).fetchone()
        if not row:
            return None
        conn().execute("UPDATE candidates SET status=? WHERE id=?", (status, cid))
        conn().commit()
    return json.loads(row["doc"])


def report_state(unit: str, year: int) -> dict:
    row = conn().execute("SELECT status, doc FROM reports WHERE unit=? AND year=?", (unit, year)).fetchone()
    if not row:
        return {"status": "создано", "history": []}
    doc = json.loads(row["doc"])
    doc["status"] = row["status"]
    return doc


def set_report_state(unit: str, year: int, status: str, doc: dict) -> None:
    with _lock:
        payload = {k: v for k, v in doc.items() if k != "status"}
        conn().execute("INSERT OR REPLACE INTO reports(unit,year,status,doc) VALUES(?,?,?,?)",
                       (unit, year, status, json.dumps(payload, ensure_ascii=False)))
        conn().commit()


def add_version(unit: str, year: int, approved_by: str, snapshot: dict) -> int:
    with _lock:
        row = conn().execute("SELECT COALESCE(MAX(version),0) v FROM report_versions WHERE unit=? AND year=?", (unit, year)).fetchone()
        version = row["v"] + 1
        conn().execute("INSERT INTO report_versions(unit,year,version,approved_by,approved_at,snapshot) VALUES(?,?,?,?,?,?)",
                       (unit, year, version, approved_by, now(), json.dumps(snapshot, ensure_ascii=False)))
        conn().commit()
    return version


def versions(unit: str, year: int) -> list[dict]:
    rows = conn().execute("SELECT id,version,approved_by,approved_at FROM report_versions WHERE unit=? AND year=? ORDER BY version DESC",
                          (unit, year)).fetchall()
    return [dict(r) for r in rows]


def version_snapshot(unit: str, year: int, version: int) -> dict | None:
    row = conn().execute("SELECT snapshot FROM report_versions WHERE unit=? AND year=? AND version=?", (unit, year, version)).fetchone()
    return json.loads(row["snapshot"]) if row else None


def notify(text: str, person: str | None = None, role: str | None = None, unit: str | None = None, link: str = "") -> None:
    with _lock:
        conn().execute("INSERT INTO notifications(person,role,unit,text,link,at) VALUES(?,?,?,?,?,?)",
                       (person, role, unit, text, link, now()))
        conn().commit()


def notifications(position: dict, limit: int = 30) -> list[dict]:
    rows = conn().execute(
        "SELECT * FROM notifications WHERE person=? OR (role=? AND (unit IS NULL OR unit=?)) ORDER BY id DESC LIMIT ?",
        (position.get("person"), position.get("role"), position.get("unit"), limit)).fetchall()
    return [dict(r) for r in rows]


def mark_notifications_read(position: dict) -> None:
    with _lock:
        conn().execute("UPDATE notifications SET read=1 WHERE person=? OR (role=? AND (unit IS NULL OR unit=?))",
                       (position.get("person"), position.get("role"), position.get("unit")))
        conn().commit()


def campaign(year: int) -> dict | None:
    row = conn().execute("SELECT * FROM campaigns WHERE year=? ORDER BY id DESC LIMIT 1", (year,)).fetchone()
    return dict(row) if row else None


def set_campaign(year: int, deadline: str, title: str, by: str) -> None:
    with _lock:
        conn().execute("INSERT INTO campaigns(year,deadline,title,created_by) VALUES(?,?,?,?)", (year, deadline, title, by))
        conn().commit()


def save_audit(doc: dict) -> str:
    aid = uuid.uuid4().hex[:12]
    with _lock:
        conn().execute("INSERT INTO audits(id,at,doc) VALUES(?,?,?)", (aid, now(), json.dumps(doc, ensure_ascii=False)))
        conn().commit()
    return aid


def get_audit(aid: str) -> dict | None:
    row = conn().execute("SELECT doc FROM audits WHERE id=?", (aid,)).fetchone()
    return json.loads(row["doc"]) if row else None


def add_person(doc: dict) -> dict:
    with _lock:
        conn().execute("INSERT OR REPLACE INTO persons(id,role,unit,doc) VALUES(?,?,?,?)",
                       (doc["id"], doc["role"], doc.get("unit"), json.dumps(doc, ensure_ascii=False)))
        conn().commit()
    return doc

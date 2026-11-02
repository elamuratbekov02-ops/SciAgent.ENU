"""Сыртқы дереккөздер: Crossref, OpenAlex және Smart.ENU мен Platonus-қа арналған сынақ адаптерлері."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from . import store, validators
from .catalog import SMARTENU_FIELDS, SMARTENU_TYPE
from .names import norm_title

UA = "SciAgent.ENU/0.1 (demo)"
TIMEOUT = 12
DOI_RX = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>)\]]+", re.I)
ORCID_RX = re.compile(r"\b(\d{4}-\d{4}-\d{4}-\d{3}[\dXx])\b")


def _get_json(url: str, headers: dict | None = None) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def find_doi(text: str) -> str | None:
    m = DOI_RX.search(text or "")
    return m.group(0).rstrip(".,;") if m else None


def find_orcid(text: str) -> str | None:
    m = ORCID_RX.search(text or "")
    return m.group(1) if m else None


def _crossref_fields(msg: dict) -> dict:
    authors = []
    for a in msg.get("author", []) or []:
        name = " ".join(x for x in (a.get("family"), a.get("given")) if x)
        if name:
            authors.append(name)
    year = ""
    for key in ("published-print", "published-online", "issued", "published"):
        parts = (msg.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            year = str(parts[0][0])
            break
    raw_type = msg.get("type", "")
    rec_type = "article"
    if raw_type in ("proceedings-article", "proceedings"):
        rec_type = "conference"
    elif raw_type in ("book", "monograph", "edited-book"):
        rec_type = "monograph"
    title = (msg.get("title") or [""])[0]
    source = (msg.get("container-title") or [""])[0]
    issue = "/".join(x for x in (msg.get("volume"), msg.get("issue")) if x)
    fields = {"title": re.sub(r"\s+", " ", title).strip(), "source": source, "year": year, "issue": issue,
              "pages": msg.get("page", "") or "", "doi": msg.get("DOI", ""), "publisher": msg.get("publisher", ""),
              "city": msg.get("publisher-location", "")}
    if msg.get("ISSN"):
        fields["issn"] = msg["ISSN"][0]
    if msg.get("ISBN"):
        fields["isbn"] = msg["ISBN"][0]
    return {"type": rec_type, "fields": {k: v for k, v in fields.items() if v}, "authors": authors, "verified_by": "Crossref"}


def crossref_by_doi(doi: str) -> dict | None:
    data = _get_json("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/"))
    return _crossref_fields(data["message"]) if data and data.get("message") else None


def crossref_by_title(title: str) -> dict | None:
    query = urllib.parse.urlencode({"query.bibliographic": title, "rows": 3})
    data = _get_json("https://api.crossref.org/works?" + query)
    if not data:
        return None
    wanted = norm_title(title)
    for item in (data.get("message") or {}).get("items", []):
        cand = norm_title((item.get("title") or [""])[0])
        if cand and (cand == wanted or (len(wanted) > 25 and (cand in wanted or wanted in cand))):
            return _crossref_fields(item)
    return None


def crossref_by_orcid(orcid: str, rows: int = 20) -> list[dict]:
    query = urllib.parse.urlencode({"filter": f"orcid:{orcid}", "rows": rows, "sort": "published", "order": "desc"})
    data = _get_json("https://api.crossref.org/works?" + query)
    if not data:
        return []
    return [_crossref_fields(item) for item in (data.get("message") or {}).get("items", [])]


def openalex_by_orcid(orcid: str, rows: int = 20) -> list[dict]:
    key = os.environ.get("OPENALEX_API_KEY")
    if not key:
        return []
    query = urllib.parse.urlencode({"filter": f"author.orcid:{orcid}", "per-page": rows, "sort": "publication_year:desc", "api_key": key})
    data = _get_json("https://api.openalex.org/works?" + query)
    out = []
    for w in (data or {}).get("results", []):
        loc = (w.get("primary_location") or {}).get("source") or {}
        biblio = w.get("biblio") or {}
        pages = "-".join(x for x in (biblio.get("first_page"), biblio.get("last_page")) if x)
        fields = {"title": w.get("title") or "", "source": loc.get("display_name") or "", "year": str(w.get("publication_year") or ""),
                  "issue": biblio.get("issue") or "", "pages": pages, "doi": (w.get("doi") or "").replace("https://doi.org/", "")}
        if loc.get("issn_l"):
            fields["issn"] = loc["issn_l"]
        out.append({"type": "article", "fields": {k: v for k, v in fields.items() if v},
                    "authors": [a["author"]["display_name"] for a in w.get("authorships", []) if a.get("author")], "verified_by": "OpenAlex"})
    return out


def index_hint(issn: str = "", source: str = "") -> dict | None:
    """Индексті модельдің болжамымен емес, бұрын тексерілген жазбалар бойынша анықтайды."""
    tokens = set(validators.extract_issn(issn or ""))
    src = norm_title(source)
    for r in store.records():
        if r["type"] != "article" or not r["attrs"].get("index"):
            continue
        rt = set(validators.extract_issn(r["fields"].get("issn", "")))
        if (tokens and tokens & rt) or (src and len(src) > 10 and src == norm_title(r["fields"].get("source", ""))):
            return {"index": r["attrs"]["index"], "basis": "Ранее зарегистрированный журнал"}
    return None


def smartenu_payload(rec: dict) -> dict:
    """Жазбаны Smart.ENU «Ғылыми жұмыстар» формасының өрістеріне түрлендіреді (сынақ адаптері)."""
    persons = store.persons()
    fields = {}
    for key, target in SMARTENU_FIELDS.items():
        value = rec["fields"].get(key)
        if value and target not in fields:
            fields[target] = value
    idx = rec["attrs"].get("index")
    science_type = SMARTENU_TYPE.get((rec["type"], idx)) or SMARTENU_TYPE.get((rec["type"], None)) or "free"
    return {
        "scienceWorkType": science_type,
        **fields,
        "coauthorsInternal": [{"userID": a, "fullName": persons.get(a, {}).get("display_name", a)} for a in rec.get("author_ids", [])
                              if persons.get(a, {}).get("role") != "external"],
        "coauthorsExternal": [persons.get(a, {}).get("display_name", a) for a in rec.get("author_ids", [])
                              if persons.get(a, {}).get("role") == "external"] + rec.get("external_authors", []),
        "attachments": [{"filename": e["filename"]} for e in rec.get("evidence", [])],
        "_section605": rec.get("sections", []),
    }

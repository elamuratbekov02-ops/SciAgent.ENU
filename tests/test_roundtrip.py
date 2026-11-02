"""Шыққан Excel қайта оқылады және нысан құрылымын сақтайды: 56 тізім мен жолдар орнында."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("SCIAGENT_DB", str(Path(tempfile.mkdtemp()) / "test.db"))
os.environ.setdefault("SCIAGENT_UPLOADS", str(Path(tempfile.mkdtemp()) / "uploads"))
os.environ["SCIAGENT_AI"] = "off"

from app import audit, reporting, services, store  # noqa: E402
from app.form_parser import read_blocks  # noqa: E402


def test_exported_report_can_be_read_back_and_audited(tmp_path):
    store.seed_if_empty(force=True)
    path = tmp_path / "report.xlsx"
    path.write_bytes(reporting.f605_bytes(services.snapshot("mgmt", 2025), pii=False))
    parsed = read_blocks(path)
    assert len(parsed["blocks"]) == 56
    rows = sum(len(b["rows"]) for b in parsed["blocks"])
    assert rows == 164
    result = audit.run_audit(path)
    assert result["rows"] == 164
    assert result["duplicate_rows"] >= 7
    assert result["errors"] > 0
    joined = str(result)
    assert "+7 7" not in joined and "@" not in joined

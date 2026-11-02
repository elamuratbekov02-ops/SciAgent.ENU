"""Нақты есепті жергілікті аудиттейді. Шығысында адам аты жоқ, тек сандар мен жол нөмірлері.

Қолданылуы:  python tools/audit_real_report.py "<есеп.xlsx>"
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SCIAGENT_DB"] = str(Path(tempfile.mkdtemp()) / "audit.db")

from app import audit, store  # noqa: E402

store.seed_if_empty()
result = audit.run_audit(sys.argv[1])
print(json.dumps({k: result[k] for k in ("blocks", "rows", "publications", "errors", "warnings", "duplicate_rows", "pps_duplicate_rows", "compare")}, ensure_ascii=False, indent=1))
for c in result["counts"]:
    print(c["level"], c["count"], c["label"])

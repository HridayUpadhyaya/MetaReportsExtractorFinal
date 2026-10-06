from __future__ import annotations
import json
from pathlib import Path

DEFAULT = {"processed": {}, "rows": [], "failed": []}

def load_state(path: Path) -> dict:
    if not path.exists():
        return {"processed": {}, "rows": [], "failed": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for k,v in DEFAULT.items():
            data.setdefault(k, v.copy() if isinstance(v, dict) else list(v))
        return data
    except Exception:
        return {"processed": {}, "rows": [], "failed": []}


def save_state(path: Path, state: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def merge_rows(existing: list[dict], new_rows: list[dict]) -> list[dict]:
    by_key = {}
    for r in existing + new_rows:
        key = (r.get("period_end"), r.get("platform"), r.get("policy_category"))
        by_key[key] = r
    porder = {"Facebook": 0, "Instagram": 1, "Threads": 2}
    return sorted(by_key.values(), key=lambda r: (r.get("period_end") or "", porder.get(r.get("platform"), 99), r.get("policy_order", 999), r.get("policy_category") or ""))

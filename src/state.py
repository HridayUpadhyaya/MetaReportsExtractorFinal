from __future__ import annotations

import json
from pathlib import Path


DEFAULT = {
    "processed": {},
    "processed_editions": {},
    "rows": [],
    "failed": [],
}


def load_state(path: Path) -> dict:
    if not path.exists():
        return {
            "processed": {},
            "processed_editions": {},
            "rows": [],
            "failed": [],
        }

    try:
        data = json.loads(path.read_text(encoding="utf-8"))

        for key, default_value in DEFAULT.items():
            if isinstance(default_value, dict):
                data.setdefault(key, {})
            else:
                data.setdefault(key, [])

        return data

    except Exception:
        return {
            "processed": {},
            "processed_editions": {},
            "rows": [],
            "failed": [],
        }


def save_state(path: Path, state: dict):
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(
            state,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def merge_rows(existing: list[dict], new_rows: list[dict]) -> list[dict]:
    by_key = {}

    for row in existing + new_rows:
        key = (
            row.get("period_end"),
            row.get("platform"),
            row.get("policy_category"),
        )

        by_key[key] = row

    platform_order = {
        "Facebook": 0,
        "Instagram": 1,
        "Threads": 2,
    }

    return sorted(
        by_key.values(),
        key=lambda row: (
            row.get("period_end") or "",
            platform_order.get(row.get("platform"), 99),
            row.get("policy_order", 999),
            row.get("policy_category") or "",
        ),
    )

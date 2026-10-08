"""Publish only the fields needed by the public report explorer."""
from .exporter import _failed_report_to_text


PUBLIC_FIELDS = (
    "month", "period_start", "period_end", "report_published", "platform",
    "policy_category", "content_actioned_raw", "content_actioned_numeric",
    "proactive_rate", "total_user_grievances", "source_notes",
)


def public_dataset(rows, failed, status):
    # This order must match Master Data; the browser copies the original Excel
    # cells to retain dates, styles, and Python's rounding of derived estimates.
    order = {"Facebook": 0, "Instagram": 1, "Threads": 2}
    ordered = sorted(rows, key=lambda r: (
        r.get("period_end") or "", order.get(r.get("platform"), 99),
        r.get("policy_order", 999), r.get("policy_category") or "",
    ))
    return {
        "schema_version": 1,
        "status": status,
        "rows": [dict({key: row.get(key) for key in PUBLIC_FIELDS}, workbook_row=i)
                 for i, row in enumerate(ordered, 2)],
        "excluded_reports": [{
            "period_end": item.get("audit", {}).get("period_end") if isinstance(item, dict) else None,
            "message": _failed_report_to_text(item),
        } for item in failed],
    }

from __future__ import annotations
import re
from collections import Counter, defaultdict

KNOWN_CATEGORIES = {
    "Adult Nudity and Sexual Activity",
    "Bullying and Harassment",
    "Child Endangerment - Nudity and Physical Abuse",
    "Child Endangerment - Sexual Exploitation",
    "Child Nudity and Sexual Exploitation",
    "Dangerous Organizations and Individuals: Organized Hate",
    'Dangerous Organizations and Individuals: Terrorism (formerly "Terrorist Propaganda")',
    "Hate Speech", "Regulated Goods: Drugs", "Regulated Goods: Firearms",
    "Suicide and Self-Injury", "Spam", "Violent and Graphic Content", "Violence and Incitement",
}


def validate_report(parsed: dict) -> dict:
    rows = parsed.get("rows", [])
    report_issues: list[str] = []
    row_issues: dict[int, list[str]] = defaultdict(list)

    if not parsed.get("period_start") or not parsed.get("period_end"):
        report_issues.append("missing_reporting_period")
    if not rows:
        report_issues.append("no_policy_rows")

    by_platform = defaultdict(list)
    for i, r in enumerate(rows):
        by_platform[r["platform"]].append((i, r))
        rate = r.get("proactive_rate")
        num = r.get("content_actioned_numeric")
        raw = str(r.get("content_actioned_raw") or "")
        if rate is None or not (0 <= rate <= 1):
            row_issues[i].append("proactive_rate_out_of_range")
        if num is None or num < 0:
            row_issues[i].append("content_actioned_invalid")
        if re.fullmatch(r"\s*\d+\.\s*", raw):
            row_issues[i].append("suspicious_truncated_number")
        if r.get("platform") in {"Facebook", "Instagram"} and isinstance(num, (int, float)) and num < 100:
            row_issues[i].append("suspiciously_small_fb_ig_value")
        if r.get("policy_category") not in KNOWN_CATEGORIES:
            row_issues[i].append("unknown_policy_category")

    expected = parsed.get("expected_policy_count")
    for platform, items in by_platform.items():
        cats = [r["policy_category"] for _, r in items]
        dupes = [c for c, n in Counter(cats).items() if n > 1]
        if dupes:
            report_issues.append(f"duplicate_categories:{platform}:{'|'.join(dupes)}")
        if len(items) < 7 or len(items) > 20:
            report_issues.append(f"implausible_policy_row_count:{platform}:{len(items)}")
        if expected is not None and len(items) != expected:
            report_issues.append(f"expected_{expected}_policy_rows:{platform}:found_{len(items)}")

    # If a report explicitly declares one policy count, every content table should match it.
    strict_ok = not report_issues and not row_issues
    for i, r in enumerate(rows):
        issues = row_issues.get(i, [])
        r["validation_status"] = "ok" if not issues and not report_issues else "review"
        r["validation_issues"] = issues + report_issues

    return {
        "ok": strict_ok,
        "report_issues": report_issues,
        "row_issue_count": len(row_issues),
        "rows": rows,
    }

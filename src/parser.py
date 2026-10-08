from __future__ import annotations
import io
import re
from collections import defaultdict
from datetime import date, datetime
from dateutil import parser as dateparser
import pdfplumber
from .normalize import clean_text, normalize_category, parse_number, parse_rate

PLATFORMS = ["Facebook", "Instagram", "Threads"]


def _parse_date_token(s: str, default_year: int | None = None) -> date | None:
    s = clean_text(s)
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return date.fromisoformat(s)
        default = datetime(default_year or 2000, 1, 1)
        return dateparser.parse(s, fuzzy=True, dayfirst=True, default=default).date()
    except Exception:
        return None


def _find_period(text: str) -> tuple[date | None, date | None]:
    patterns = [
        r"(?:period\s+(?:from|of)|between|from)\s*(\d{4}-\d{2}-\d{2})\s*(?:-|–|—|to|and)\s*(\d{4}-\d{2}-\d{2})",
        r"(\d{4}-\d{2}-\d{2})\s*(?:-|–|—|to|and)\s*(\d{4}-\d{2}-\d{2})",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            start, end = _parse_date_token(m.group(1)), _parse_date_token(m.group(2))
            if start and end and start <= end:
                return start, end
    patterns = [
        r"(?:period|between|from)\s+(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+(?:\s+\d{4})?)\s*(?:-|–|—|to|and)\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})",
        r"(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})\s*(?:-|–|—|to)\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})",
        r"(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s+\d{4})\s*(?:-|–|—|to)\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s+\d{4})",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            end = _parse_date_token(m.group(2))
            start = _parse_date_token(m.group(1), end.year if end else None)
            if start and end and start <= end:
                return start, end
    return None, None


def _find_published(text: str) -> str | None:
    patterns = [
        r"(?:published|publication date)\s*(?:on)?\s*[:\-]?\s*(\d{4}-\d{2}-\d{2})",
        r"(?:published|publication date)\s*(?:on)?\s*[:\-]?\s*(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s+\d{4})",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            token = clean_text(m.group(1))
            d = _parse_date_token(token)
            return d.isoformat() if d else token
    return None


def _find_grievances(text: str) -> dict[str, int]:
    flat = clean_text(text)
    out: dict[str, int] = {}
    for platform in PLATFORMS:
        for hit in re.finditer(rf"\b{re.escape(platform)}\b", flat, re.I):
            section = flat[hit.end():hit.end() + 700]
            m = re.search(
                r"^\s*(?:Between|For the period|During the period).{0,350}?received\s+([\d,]+)\s+(?:user\s+)?(?:reports|complaints|grievances)",
                section, re.I
            )
            if m:
                out[platform] = int(m.group(1).replace(",", ""))
                break
    return out


def _platform_from_context(context: str) -> str | None:
    positions = [(context.lower().rfind(p.lower()), p) for p in PLATFORMS]
    positions = [x for x in positions if x[0] >= 0]
    return max(positions)[1] if positions else None


def _header_indexes(rows: list[list[str | None]]) -> tuple[int, int, int, int] | None:
    for header_i in range(min(6, len(rows))):
        header = [clean_text(x).lower() for x in rows[header_i]]
        action_i = next((i for i, x in enumerate(header) if "action" in x and ("content" in x or "piece" in x)), None)
        rate_i = next((i for i, x in enumerate(header) if "proactive" in x and ("rate" in x or "%" in x)), None)
        category_i = next((i for i, x in enumerate(header) if any(k in x for k in ["policy", "category", "standard", "area"])), 0)
        if action_i is not None and rate_i is not None:
            return header_i, category_i, action_i, rate_i
    return None


def _expected_policy_counts(text: str) -> dict[str, int]:
    """Read platform-specific counts from the report prose.

    Older Meta India reports legitimately had 13 Facebook policy areas but only
    12 Instagram policy areas.  The previous validator captured only the first
    number and incorrectly applied 13 to every platform.
    """
    flat = clean_text(text)
    out: dict[str, int] = {}

    # e.g. "13 policy areas on Facebook and 12 policy areas on Instagram"
    for m in re.finditer(r"(\d{1,2})\s+policy\s+areas?\s+on\s+(Facebook|Instagram|Threads)", flat, re.I):
        out[m.group(2).title()] = int(m.group(1))

    # e.g. "13 policy areas on Facebook, Instagram and Threads"
    m = re.search(
        r"(?:breakdown[^.]{0,220}?)?in\s+(\d{1,2})\s+policy\s+areas?\s+on\s+([^\.]{1,100})",
        flat,
        re.I,
    )
    if m:
        n = int(m.group(1))
        platforms_phrase = m.group(2)
        for p in PLATFORMS:
            if re.search(rf"\b{p}\b", platforms_phrase, re.I):
                out.setdefault(p, n)

    # Some older prose is "13 policies for Facebook and 12 policies for Instagram".
    for m in re.finditer(r"(\d{1,2})\s+polic(?:y|ies)(?:\s+areas?)?\s+(?:for|on)\s+(Facebook|Instagram|Threads)", flat, re.I):
        out[m.group(2).title()] = int(m.group(1))

    return out


def _rate_cell_index(cells: list[str]) -> int | None:
    for i in range(len(cells) - 1, -1, -1):
        if "%" in cells[i]:
            try:
                parse_rate(cells[i])
                return i
            except ValueError:
                pass
    return None


def _fallback_data_row(row: list[str | None]) -> tuple[str, str, str] | None:
    """Recognize a content-policy row even when a continued table has no header.

    Grievance tables are naturally excluded because they do not contain a
    proactive-rate percentage column.
    """
    cells = [clean_text(x) for x in row]
    if len(cells) < 3:
        return None
    rate_i = _rate_cell_index(cells)
    if rate_i is None or rate_i < 2:
        return None

    # Category is the leftmost non-empty text before the numeric columns.
    category_i = next((i for i, x in enumerate(cells[:rate_i]) if x), None)
    if category_i is None:
        return None
    raw_cat = cells[category_i]
    if any(x in raw_cat.lower() for x in ["policy area", "category", "content actioned", "total"]):
        return None

    # Prefer the first fully parseable number after the category. This selects
    # the report's first Content Actioned representation and still supports L.
    raw_action = None
    for x in cells[category_i + 1:rate_i]:
        if not x:
            continue
        try:
            parse_number(x)
            raw_action = x
            break
        except ValueError:
            continue
    if raw_action is None:
        return None

    raw_rate = cells[rate_i]
    try:
        parse_rate(raw_rate)
    except ValueError:
        return None
    return raw_cat, raw_action, raw_rate


def parse_pdf(pdf_bytes: bytes, title: str | None = None, source_url: str | None = None) -> dict:
    candidates: list[dict] = []
    page_texts: list[str] = []
    last_policy_platform: str | None = None
    platform_order = defaultdict(int)

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            page_texts.append(text)
            page_platform = _platform_from_context(text)
            try:
                table_objs = page.find_tables()
            except Exception:
                table_objs = []

            for table_obj in table_objs:
                rows = table_obj.extract() or []
                idxs = _header_indexes(rows)

                if idxs:
                    header_i, category_i, action_i, rate_i = idxs
                    try:
                        top = max(0, table_obj.bbox[1] - 240)
                        context = page.crop((0, top, page.width, table_obj.bbox[1])).extract_text() or text[:3500]
                    except Exception:
                        context = text[:3500]
                    platform = _platform_from_context(context) or page_platform or last_policy_platform
                    if not platform:
                        continue
                    last_policy_platform = platform

                    for r in rows[header_i + 1:]:
                        if max(category_i, action_i, rate_i) >= len(r):
                            continue
                        raw_cat = clean_text(r[category_i])
                        raw_action = clean_text(r[action_i])
                        raw_rate = clean_text(r[rate_i])
                        if not raw_cat or not raw_action or not raw_rate:
                            continue
                        if any(x in raw_cat.lower() for x in ["total", "policy area", "category"]):
                            continue
                        try:
                            numeric = parse_number(raw_action)
                            rate = parse_rate(raw_rate)
                        except ValueError:
                            continue
                        platform_order[platform] += 1
                        candidates.append({
                            "platform": platform,
                            "policy_order": platform_order[platform],
                            "raw_policy_category": raw_cat,
                            "policy_category": normalize_category(raw_cat),
                            "content_actioned_raw": raw_action,
                            "content_actioned_numeric": numeric,
                            "proactive_rate": rate,
                            "source_page": page_num,
                            "source_url": source_url,
                            "extraction_method": "deterministic_table",
                            "confidence": 0.99,
                        })
                    continue

                # Continuation-table fallback. A Meta policy table can spill to
                # the next page without repeating its header; the old parser
                # dropped every continuation row.
                platform = page_platform or last_policy_platform
                if not platform:
                    continue
                for r in rows:
                    detected = _fallback_data_row(r)
                    if not detected:
                        continue
                    raw_cat, raw_action, raw_rate = detected
                    try:
                        numeric = parse_number(raw_action)
                        rate = parse_rate(raw_rate)
                    except ValueError:
                        continue
                    platform_order[platform] += 1
                    candidates.append({
                        "platform": platform,
                        "policy_order": platform_order[platform],
                        "raw_policy_category": raw_cat,
                        "policy_category": normalize_category(raw_cat),
                        "content_actioned_raw": raw_action,
                        "content_actioned_numeric": numeric,
                        "proactive_rate": rate,
                        "source_page": page_num,
                        "source_url": source_url,
                        "extraction_method": "deterministic_table_continuation",
                        "confidence": 0.98,
                    })

    # De-duplicate the same policy if both the regular and continuation paths
    # saw it. Prefer the first/high-confidence occurrence.
    rows_out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in sorted(candidates, key=lambda r: (r["source_page"], -r["confidence"], r["policy_order"])):
        key = (row["platform"], row["policy_category"])
        if key in seen:
            continue
        seen.add(key)
        rows_out.append(row)

    # Re-number after de-duplication.
    counters = defaultdict(int)
    for row in rows_out:
        counters[row["platform"]] += 1
        row["policy_order"] = counters[row["platform"]]

    full_text = "\n".join(page_texts)
    start, end = _find_period(full_text)
    grievances = _find_grievances(full_text)
    published = _find_published(full_text)
    month = end.strftime("%b-%Y") if end else "Unknown"
    for row in rows_out:
        row.update({
            "month": month,
            "period_start": start.isoformat() if start else None,
            "period_end": end.isoformat() if end else None,
            "report_published": published,
            "total_user_grievances": grievances.get(row["platform"]),
        })

    expected_counts = _expected_policy_counts(full_text)
    return {
        "rows": rows_out,
        "period_start": start.isoformat() if start else None,
        "period_end": end.isoformat() if end else None,
        "report_published": published,
        "grievances": grievances,
        "expected_policy_counts": expected_counts,
        # Backwards-compatibility only when a single universal count exists.
        "expected_policy_count": next(iter(set(expected_counts.values()))) if expected_counts and len(set(expected_counts.values())) == 1 else None,
        "text": full_text,
        "title": title,
        "source_url": source_url,
    }

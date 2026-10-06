from __future__ import annotations
import io
import re
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
        r"(?:period|between|from)\s+(\d{1,2}\s+[A-Za-z]+(?:\s+\d{4})?)\s*(?:-|–|—|to|and)\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s*(?:-|–|—|to)\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        r"(\d{1,2}\s+[A-Za-z]+,?\s+\d{4})\s*(?:-|–|—|to)\s*(\d{1,2}\s+[A-Za-z]+,?\s+\d{4})",
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
        r"(?:published|publication date)\s*(?:on)?\s*[:\-]?\s*(\d{1,2}\s+[A-Za-z]+,?\s+\d{4})",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return clean_text(m.group(1))
    return None


def _find_grievances(text: str) -> dict[str, int]:
    flat = clean_text(text)
    out: dict[str, int] = {}
    # Grievance sections use a platform heading immediately followed by a sentence
    # such as "Between ... we received 22,516 reports". Requiring "Between" close
    # to the heading prevents the earlier content-actioned table headings from
    # being mistaken for grievance sections.
    for platform in PLATFORMS:
        for hit in re.finditer(rf"\b{re.escape(platform)}\b", flat, re.I):
            section = flat[hit.end():hit.end() + 650]
            m = re.search(
                r"^\s*(?:Between|For the period|During the period).{0,300}?received\s+([\d,]+)\s+(?:user\s+)?(?:reports|complaints|grievances)",
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
    for header_i in range(min(5, len(rows))):
        header = [clean_text(x).lower() for x in rows[header_i]]
        action_i = next((i for i, x in enumerate(header) if "action" in x and ("content" in x or "piece" in x)), None)
        rate_i = next((i for i, x in enumerate(header) if "proactive" in x and ("rate" in x or "%" in x)), None)
        category_i = next((i for i, x in enumerate(header) if any(k in x for k in ["policy", "category", "standard", "area"])), 0)
        if action_i is not None and rate_i is not None:
            return header_i, category_i, action_i, rate_i
    return None


def _expected_policy_count(text: str) -> int | None:
    m = re.search(r"breakdown[^.]{0,160}?in\s+(\d{1,2})\s+policy areas", clean_text(text), re.I)
    return int(m.group(1)) if m else None


def parse_pdf(pdf_bytes: bytes, title: str | None = None, source_url: str | None = None) -> dict:
    rows_out: list[dict] = []
    page_texts: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            page_texts.append(text)
            try:
                tables = page.find_tables()
            except Exception:
                tables = []
            for table_obj in tables:
                rows = table_obj.extract() or []
                idxs = _header_indexes(rows)
                if not idxs:
                    continue
                header_i, category_i, action_i, rate_i = idxs
                try:
                    top = max(0, table_obj.bbox[1] - 220)
                    context = page.crop((0, top, page.width, table_obj.bbox[1])).extract_text() or text[:3000]
                except Exception:
                    context = text[:3000]
                platform = _platform_from_context(context) or _platform_from_context(text)
                if not platform:
                    continue
                policy_order = 0
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
                    policy_order += 1
                    rows_out.append({
                        "platform": platform,
                        "policy_order": policy_order,
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
    return {
        "rows": rows_out,
        "period_start": start.isoformat() if start else None,
        "period_end": end.isoformat() if end else None,
        "report_published": published,
        "grievances": grievances,
        "expected_policy_count": _expected_policy_count(full_text),
        "text": full_text,
        "title": title,
        "source_url": source_url,
    }

from __future__ import annotations
from collections import defaultdict
from copy import copy
from datetime import datetime, timezone
from pathlib import Path
from openpyxl import load_workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.chart.series import SeriesLabel


def _copy_style_row(ws, source_row: int, target_row: int, max_col: int):
    for c in range(1, max_col + 1):
        src = ws.cell(source_row, c)
        dst = ws.cell(target_row, c)
        if src.has_style:
            dst._style = copy(src._style)
        dst.number_format = src.number_format
        dst.alignment = copy(src.alignment)
        dst.font = copy(src.font)
        dst.fill = copy(src.fill)
        dst.border = copy(src.border)


def _proactive(r: dict) -> int:
    return int(round(float(r.get("content_actioned_numeric") or 0) * float(r.get("proactive_rate") or 0)))


def build_workbook(template: Path, output: Path, rows: list[dict], failed_reports: list[str] | None = None) -> None:
    failed_reports = failed_reports or []
    porder = {"Facebook": 0, "Instagram": 1, "Threads": 2}
    rows = sorted(rows, key=lambda r: (r.get("period_end") or "", porder.get(r.get("platform"), 99), r.get("policy_order", 999), r.get("policy_category") or ""))
    wb = load_workbook(template)

    md = wb["Master Data"]
    style_row = 2
    styles = [copy(md.cell(style_row, c)._style) for c in range(1, 12)]
    formats = [md.cell(style_row, c).number_format for c in range(1, 12)]
    if md.max_row > 1:
        md.delete_rows(2, md.max_row - 1)
    for i, r in enumerate(rows, start=2):
        for c in range(1, 12):
            md.cell(i, c)._style = copy(styles[c-1])
            md.cell(i, c).number_format = formats[c-1]
        vals = [
            r.get("month"), r.get("period_start"), r.get("period_end"), r.get("report_published"),
            r.get("platform"), r.get("policy_category"), r.get("content_actioned_raw"),
            r.get("content_actioned_numeric"), r.get("proactive_rate"), _proactive(r), r.get("total_user_grievances"),
        ]
        for c, v in enumerate(vals, 1):
            md.cell(i, c).value = v
    note_row = len(rows) + 3
    md.cell(note_row,1).value = "Note: 'Total User Grievances Received' is the platform-month total (not broken down by category) and is repeated on every category row for that platform-month, so it can be filtered/pivoted alongside category-level data. 'Proactive Actions by AI (est.)' = Content Actioned x Proactive Rate."
    md.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=11)
    md.freeze_panes = "A2"
    md.auto_filter.ref = f"A1:K{max(2, len(rows)+1)}"

    # Precompute monthly summary values. This avoids relying on Excel recalculation.
    groups = defaultdict(list)
    for r in rows:
        groups[(r.get("month"), r.get("period_end"), r.get("platform"))].append(r)
    summary = []
    for key, rs in sorted(groups.items(), key=lambda kv: (kv[0][1] or "", kv[0][2] or "")):
        total = int(round(sum(float(r.get("content_actioned_numeric") or 0) for r in rs)))
        proactive = sum(_proactive(r) for r in rs)
        rate = proactive / total if total else None
        grievances = next((r.get("total_user_grievances") for r in rs if r.get("total_user_grievances") is not None), None)
        summary.append((*key, total, proactive, rate, grievances))

    ms = wb["Monthly Summary"]
    style_source = 2
    if ms.max_row > 1:
        ms.delete_rows(2, ms.max_row - 1)
    for i, rec in enumerate(summary, start=2):
        if i > 2:
            _copy_style_row(ms, 1 if style_source > ms.max_row else style_source, i, 7)
        for c, v in enumerate(rec, 1):
            ms.cell(i,c).value = v
    ms.freeze_panes = "A2"

    # Trend table: one row per month. Keep the template's two platform-specific charts.
    tc = wb["Trend Charts"]
    tc._charts = []
    if tc.max_row > 1:
        tc.delete_rows(2, tc.max_row - 1)
    month_map = defaultdict(dict)
    for month, period_end, platform, total, proactive, rate, grievances in summary:
        month_map[(month, period_end)][platform] = (total, grievances)
    for i, ((month, period_end), pmap) in enumerate(sorted(month_map.items(), key=lambda kv: kv[0][1] or ""), start=2):
        tc.cell(i,1).value = month
        tc.cell(i,2).value = period_end
        tc.cell(i,3).value = pmap.get("Facebook", (None,None))[0]
        tc.cell(i,4).value = pmap.get("Facebook", (None,None))[1]
        tc.cell(i,5).value = pmap.get("Instagram", (None,None))[0]
        tc.cell(i,6).value = pmap.get("Instagram", (None,None))[1]

    if month_map:
        end = len(month_map) + 1
        cats = Reference(tc, min_col=1, min_row=2, max_row=end)
        fb = LineChart(); fb.title = "Facebook: Content Actioned (AI) vs Grievances Received"; fb.y_axis.title="Count"; fb.x_axis.title="Month"; fb.height=10; fb.width=20
        fb.add_data(Reference(tc, min_col=3, max_col=4, min_row=1, max_row=end), titles_from_data=True)
        if len(fb.series) >= 2:
            fb.series[0].tx = SeriesLabel(v=tc.cell(1,3).value)
            fb.series[1].tx = SeriesLabel(v=tc.cell(1,4).value)
        fb.set_categories(cats); tc.add_chart(fb, "H1")
        ig = LineChart(); ig.title = "Instagram: Content Actioned (AI) vs Grievances Received"; ig.y_axis.title="Count"; ig.x_axis.title="Month"; ig.height=10; ig.width=20
        ig.add_data(Reference(tc, min_col=5, max_col=6, min_row=1, max_row=end), titles_from_data=True)
        if len(ig.series) >= 2:
            ig.series[0].tx = SeriesLabel(v=tc.cell(1,5).value)
            ig.series[1].tx = SeriesLabel(v=tc.cell(1,6).value)
        ig.set_categories(cats); tc.add_chart(ig, "H26")

    notes = wb["Data Notes"]
    periods = [r.get("period_end") for r in rows if r.get("period_end")]
    platforms = sorted({r.get("platform") for r in rows if r.get("platform")})
    notes["A4"] = "Meta India Monthly Reports under the Information Technology (Intermediary Guidelines and Digital Media Ethics Code) Rules, 2021. Source: official Meta report PDFs discovered from Meta's Regulatory Transparency Reports hub."
    notes["A7"] = "Only reports that pass strict structural validation are included in Master Data. Suspicious/unsupported reports are written to the review folder instead of being silently accepted."
    notes["A8"] = f"{len(failed_reports)} report(s) failed download or validation in the latest run."
    if periods:
        notes["A11"] = f"{len(set(r.get('month') for r in rows))} monthly data point(s), {min(periods)} – {max(periods)}. Platforms present: {', '.join(platforms)}."
    for rr in range(28, 36):
        notes.cell(rr,1).value = None
        notes.cell(rr,3).value = None
    if not failed_reports:
        notes["A28"] = "None in the latest run."
    else:
        summaries = []
    
        for failed in failed_reports:
            if isinstance(failed, dict):
                publication = failed.get("publication_month", "Unknown publication")
                error = failed.get("error", "Unknown error")
                summaries.append(f"{publication}: {error}")
            else:
                summaries.append(str(failed))

        notes["A28"] = "\n".join(summaries[:10])
    for j, msg in enumerate(failed_reports[1:8], start=29):
        notes.cell(j,1).value = msg
    notes["A36"] = f"Generated by Meta India low-request pipeline on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}."

    output.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output)

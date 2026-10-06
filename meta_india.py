from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from src.exporter import build_workbook
from src.parser import parse_pdf
from src.state import load_state, save_state, merge_rows
from src.validate import validate_report

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "data" / "state.json"
REVIEW = ROOT / "review"
CACHE = ROOT / "cache"
OUTPUT = ROOT / "output" / "meta_india_reports_latest.xlsx"
DOCS_OUTPUT = ROOT / "docs" / "downloads" / "meta_india_reports_latest.xlsx"
TEMPLATE = ROOT / "template.xlsx"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def process_pdf_file(pdf_path: Path, source_url: str | None = None, include_review: bool = False) -> dict:
    pdf_path = Path(pdf_path).expanduser().resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    data = pdf_path.read_bytes()
    if not data.startswith(b"%PDF"):
        raise RuntimeError(f"File is not a valid PDF: {pdf_path}")

    parsed = parse_pdf(
        data,
        title=pdf_path.name,
        source_url=source_url or f"file://{pdf_path}",
    )
    result = validate_report(parsed)

    audit = {
        "filename": pdf_path.name,
        "sha256": sha256(data),
        "period_start": parsed.get("period_start"),
        "period_end": parsed.get("period_end"),
        "report_published": parsed.get("report_published"),
        "row_count": len(parsed.get("rows", [])),
        "validation": {k: v for k, v in result.items() if k != "rows"},
    }

    if not result["ok"] and not include_review:
        REVIEW.mkdir(parents=True, exist_ok=True)
        key = parsed.get("period_end") or pdf_path.stem
        (REVIEW / f"{key}_audit.json").write_text(
            json.dumps(audit, indent=2), encoding="utf-8"
        )
        raise RuntimeError(
            "Local PDF failed strict validation. "
            f"Review file: {REVIEW / f'{key}_audit.json'}"
        )

    state = load_state(STATE)
    state["rows"] = merge_rows(state.get("rows", []), result["rows"])
    state.setdefault("processed", {})[source_url or f"file://{pdf_path}"] = audit
    write_outputs(state)
    return audit


def write_outputs(state: dict) -> None:
    failed = state.get("failed", [])[-8:]
    build_workbook(TEMPLATE, OUTPUT, state.get("rows", []), failed_reports=failed)

    DOCS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OUTPUT, DOCS_OUTPUT)

    rows = state.get("rows", [])
    status = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": len(rows),
        "reports": len(state.get("processed", {})),
        "latest_period_end": max(
            [r.get("period_end") for r in rows if r.get("period_end")],
            default=None,
        ),
        "download": "downloads/meta_india_reports_latest.xlsx",
    }
    (ROOT / "docs").mkdir(parents=True, exist_ok=True)
    (ROOT / "docs" / "status.json").write_text(
        json.dumps(status, indent=2), encoding="utf-8"
    )
    save_state(STATE, state)
    print(f"Excel written: {OUTPUT}")
    print(json.dumps(status, indent=2))


def cmd_file(args):
    p = Path(args.pdf_file).expanduser().resolve()
    audit = process_pdf_file(p, include_review=args.include_review)
    print(json.dumps(audit, indent=2))


def cmd_sync(args):
    from src.browser_fetch import browser_sync_one

    profile_dir = ROOT / ".browser_profile"
    hub_cache = CACHE / "meta_hub.html"

    state = load_state(STATE)
    processed_urls = set(state.get("processed_urls", []))

    print("Opening Meta hub in a browser ONCE. No Python requests call will be made to the hub.")

    result = browser_sync_one(
        profile_dir=profile_dir,
        hub_cache=hub_cache,
        processed_urls=processed_urls,
        headed=False,
    )

    if not result.downloaded_url or not result.pdf_bytes:
        print("No new India PDF found.")
        return

    CACHE.mkdir(parents=True, exist_ok=True)

    filename = result.filename or "meta-india-report.pdf"
    pdf = CACHE / filename
    pdf.write_bytes(result.pdf_bytes)

    url = result.downloaded_url

    print(f"Fetched one PDF:\n{url}")
    print(f"Saved: {pdf}")

    audit = process_pdf_file(
        pdf,
        source_url=url,
        include_review=args.include_review,
    )

    print(json.dumps(audit, indent=2))


def cmd_direct(args):
    from src.browser_fetch import browser_download_direct

    url = args.pdf_url.strip()

    if not url.lower().startswith(("http://", "https://")):
        raise SystemExit("--pdf-url must be a real http(s) URL, not a placeholder.")

    profile_dir = ROOT / ".browser_profile"

    data, filename = browser_download_direct(
        url=url,
        profile_dir=profile_dir,
        headed=False,
    )

    CACHE.mkdir(parents=True, exist_ok=True)

    pdf = CACHE / filename
    pdf.write_bytes(data)

    print(f"Saved: {pdf}")

    audit = process_pdf_file(
        pdf,
        source_url=url,
        include_review=args.include_review,
    )

    print(json.dumps(audit, indent=2))


def main():
    ap = argparse.ArgumentParser(description="Meta India PDF -> validated Excel converter")
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("sync")
    p.add_argument("--max-new", type=int, default=1, help="Accepted for compatibility; sync fetches at most one PDF.")
    p.add_argument("--include-review", action="store_true")
    p.set_defaults(func=cmd_sync)

    p = sp.add_parser("direct")
    p.add_argument("--pdf-url", required=True)
    p.add_argument("--include-review", action="store_true")
    p.set_defaults(func=cmd_direct)

    p = sp.add_parser("file")
    p.add_argument("--pdf-file", required=True)
    p.add_argument("--include-review", action="store_true")
    p.set_defaults(func=cmd_file)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

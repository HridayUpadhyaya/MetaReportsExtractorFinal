from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from src.exporter import build_workbook
from src.site_data import public_dataset
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


class ReportValidationError(RuntimeError):
    def __init__(self, message: str, audit: dict):
        super().__init__(message)
        self.audit = audit


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def process_pdf_file(
    pdf_path: Path,
    source_url: str | None = None,
    include_review: bool = False,
    edition_key: str | None = None,
    edition_meta: dict | None = None,
) -> dict:

    pdf_path = Path(pdf_path).expanduser().resolve()

    if not pdf_path.exists():
        raise FileNotFoundError(
            f"PDF not found: {pdf_path}"
        )

    data = pdf_path.read_bytes()

    if not data.startswith(b"%PDF"):
        raise RuntimeError(
            f"File is not a valid PDF: {pdf_path}"
        )

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
        "grievances": parsed.get("grievances"),
        "expected_policy_counts": parsed.get("expected_policy_counts"),
        "row_count": len(parsed.get("rows", [])),
        "validation": {
            k: v
            for k, v in result.items()
            if k != "rows"
        },
        "row_issues": [
            {
                "platform": row.get("platform"),
                "policy_category": row.get("raw_policy_category"),
                "issues": row.get("validation_issues"),
            }
            for row in result["rows"]
            if row.get("validation_issues")
        ],
    }

    if not result["ok"] and not include_review:
        REVIEW.mkdir(
            parents=True,
            exist_ok=True,
        )

        key = (
            parsed.get("period_end")
            or pdf_path.stem
        )

        review_file = REVIEW / f"{key}_audit.json"

        review_file.write_text(
            json.dumps(
                audit,
                indent=2,
            ),
            encoding="utf-8",
        )

        raise ReportValidationError(
            "Local PDF failed strict validation. "
            f"Review file: {review_file}",
            audit,
        )

    state = load_state(STATE)

    state["rows"] = merge_rows(
        state.get("rows", []),
        result["rows"],
    )

    source_key = (
        source_url
        or f"file://{pdf_path}"
    )

    state.setdefault(
        "processed",
        {},
    )[source_key] = audit

    if edition_key:
        meta = edition_meta or {}

        state.setdefault(
            "processed_editions",
            {},
        )[edition_key] = {
            "publication_month": meta.get("month"),
            "time_period": meta.get("time_period"),
            "platform": meta.get("platform"),
            "language": meta.get("language"),
            "period_start": audit.get("period_start"),
            "period_end": audit.get("period_end"),
            "report_published": audit.get(
                "report_published"
            ),
            "sha256": audit.get("sha256"),
            "row_count": audit.get("row_count"),
        }

    write_outputs(state)

    return audit


def write_outputs(state: dict) -> None:
    # Failed attempts cease to be outstanding when their edition succeeds.
    # Keep the latest failure per edition so reruns do not inflate the count.
    unresolved = {}
    for failure in state.get("failed", []):
        if isinstance(failure, dict):
            key = failure.get("edition_key") or failure.get("url") or str(failure)
            if failure.get("edition_key") in state.get("processed_editions", {}):
                continue
        else:
            key = str(failure)
        unresolved[key] = failure
    state["failed"] = list(unresolved.values())
    failed = state["failed"]
    build_workbook(TEMPLATE, OUTPUT, state.get("rows", []), failed_reports=failed)

    DOCS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OUTPUT, DOCS_OUTPUT)

    rows = state.get("rows", [])
    status = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": len(rows),
        "reports": len(
            {
                row.get("period_end")
                for row in rows
                if row.get("period_end")
            }
        ),
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
    (ROOT / "docs" / "data.json").write_text(
        json.dumps(public_dataset(rows, failed, status), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    (ROOT / "docs" / "validation_audit.json").write_text(
        json.dumps([
            {"publication_month": item.get("publication_month"),
             "edition_key": item.get("edition_key"),
             "audit": item.get("audit"),
             "error": item.get("error") if not item.get("audit") else None}
            if isinstance(item, dict) else {"error": str(item)}
            for item in failed
        ], indent=2), encoding="utf-8",
    )
    save_state(STATE, state)
    print(f"Excel written: {OUTPUT}")
    print(json.dumps(status, indent=2))


def cmd_file(args):
    p = Path(args.pdf_file).expanduser().resolve()
    audit = process_pdf_file(p, include_review=args.include_review)
    print(json.dumps(audit, indent=2))


def cmd_sync(args):
    from src.browser_fetch import (
        browser_discover_india_monthly_reports,
        browser_download_direct,
        _safe_filename,
    )

    profile_dir = ROOT / ".browser_profile"
    hub_cache = CACHE / "meta_hub.html"

    print(
        "Opening Meta hub in a browser ONCE. "
        "No Python requests call will be made to the hub."
    )

    editions = browser_discover_india_monthly_reports(
        profile_dir=profile_dir,
        hub_cache=hub_cache,
        headed=False,
    )

    state = load_state(STATE)

    processed_editions = set(
        state.get(
            "processed_editions",
            {},
        ).keys()
    )

    pending = [
        edition
        for edition in editions
        if edition.get("edition_key")
        not in processed_editions
    ]

    print()
    print(
        f"Meta editions available: {len(editions)}"
    )

    print(
        f"Already processed editions: "
        f"{len(processed_editions)}"
    )

    print(
        f"Missing editions: {len(pending)}"
    )

    if not pending:
        print(
            "All available India Monthly Reports "
            "have already been processed."
        )

        write_outputs(state)
        return

    max_new = args.max_new

    if max_new > 0:
        pending = pending[:max_new]

    print(
        f"This run will process "
        f"{len(pending)} report(s)."
    )

    CACHE.mkdir(
        parents=True,
        exist_ok=True,
    )

    completed = 0

    for index, edition in enumerate(
        pending,
        start=1,
    ):
        edition_key = edition["edition_key"]

        publication_month = (
            edition.get("month")
            or "Unknown publication month"
        )

        time_period = (
            edition.get("time_period")
            or "Unknown"
        )

        url = edition.get("cdn_url")

        print()
        print(
            "=" * 70
        )

        print(
            f"[{index}/{len(pending)}] "
            f"Meta publication: {publication_month}"
        )

        print(
            f"Meta time period: {time_period}"
        )

        print(
            f"Edition key: {edition_key}"
        )

        print(
            "=" * 70
        )

        if not url:
            print(
                "Skipping: edition has no CDN URL."
            )
            continue

        try:
            pdf = CACHE / _safe_filename(url)
            if pdf.exists() and pdf.read_bytes().startswith(b"%PDF"):
                print(f"Using cached PDF: {pdf}")
            else:
                data, filename = browser_download_direct(
                    url=url,
                    profile_dir=profile_dir,
                    headed=False,
                )
                print(f"Downloaded {len(data)} bytes.")
                pdf = CACHE / filename
                pdf.write_bytes(data)

            print(
                f"Saved temporary PDF: {pdf}"
            )

            audit = process_pdf_file(
                pdf,
                source_url=url,
                include_review=args.include_review,
                edition_key=edition_key,
                edition_meta=edition,
            )

            print(
                "Processed reporting period:"
            )

            print(
                "  Start:",
                audit.get("period_start"),
            )

            print(
                "  End:",
                audit.get("period_end"),
            )

            print(
                "  Published:",
                audit.get("report_published"),
            )

            completed += 1

        except Exception as exc:
            print(
                f"FAILED edition "
                f"{publication_month}: {exc}"
            )

            current_state = load_state(STATE)

            current_state.setdefault(
                "failed",
                [],
            ).append(
                {
                    "edition_key": edition_key,
                    "publication_month": publication_month,
                    "url": url,
                    "error": str(exc),
                    "audit": exc.audit if isinstance(exc, ReportValidationError) else None,
                    "failed_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                }
            )

            write_outputs(current_state)

            # If Meta starts rate-limiting us,
            # stop immediately rather than continuing
            # to send requests.
            if "429" in str(exc):
                print(
                    "Meta rate limit detected. "
                    "Stopping this run safely."
                )
                break

            continue

    final_state = load_state(STATE)

    write_outputs(final_state)

    remaining = len(
        [
            edition
            for edition in editions
            if edition.get("edition_key")
            not in final_state.get(
                "processed_editions",
                {},
            )
        ]
    )

    print()
    print(
        f"Completed this run: {completed}"
    )

    print(
        f"Reports still waiting for backfill: "
        f"{remaining}"
    )

    if remaining == 0:
        print(
            "FULL HISTORY COMPLETE."
        )


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
    p.add_argument(
        "--max-new",
        type=int,
        default=15,
        help=(
            "Maximum number of missing historical reports "
            "to process per run. "
            "Use 0 to process every missing report."
        ),
    )
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
